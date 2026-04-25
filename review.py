"""
Rule review (playbook linter)
──────────────────────────────
For each (document × rule) pair:
  1. Retrieve chunks most relevant to the rule
  2. Ask the LLM to evaluate compliance
  3. Return ok / deviation / missing with explanation + citation
"""

import json
import asyncio
import os
import re
import logging
import time
from typing import Optional

import httpx
from openai import AsyncOpenAI
try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency
    genai = None
try:
    from .ingestion import list_documents, retrieve_chunks
except ImportError:
    from ingestion import list_documents, retrieve_chunks

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b")
OLLAMA_CHAT_TIMEOUT = float(os.getenv("OLLAMA_CHAT_TIMEOUT", "300"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() in {"1", "true", "yes", "on"}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REVIEW_MAX_CONCURRENCY = int(os.getenv("REVIEW_MAX_CONCURRENCY", "6"))
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")


def _init_gemini_client():
    if LLM_PROVIDER != "gemini" or genai is None:
        return None
    try:
        if GOOGLE_GENAI_USE_VERTEXAI:
            if not GOOGLE_CLOUD_PROJECT:
                logger.warning("LLM_PROVIDER=gemini but GOOGLE_CLOUD_PROJECT is not set; using local fallback")
                return None
            return genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )
        if GEMINI_API_KEY:
            return genai.Client(api_key=GEMINI_API_KEY)
        logger.warning("LLM_PROVIDER=gemini but no auth configured; using local fallback")
        return None
    except Exception:
        logger.exception("Failed to initialize Gemini client")
        return None


gemini_client = _init_gemini_client()


def _llm_mode() -> str:
    if client:
        return f"openai:{OPENAI_MODEL}"
    if LLM_PROVIDER == "ollama":
        return f"ollama:{OLLAMA_CHAT_MODEL}"
    if gemini_client:
        return f"gemini:{GEMINI_MODEL}"
    return "local_fallback"

REVIEW_SYSTEM = """\
You are a strict legal compliance reviewer. You receive text passages from a contract
and a rule from a standard playbook. Assess whether the contract complies.

Respond ONLY with a JSON object — no prose, no markdown fences.
Schema:
{
  "status": "ok" | "deviation" | "missing",
  "explanation": "<1–2 sentence explanation>",
  "quote": "<verbatim short quote ≤30 words supporting your finding, or null>",
  "location_hint": "<clause/paragraph reference if discernible, or null>"
}

Status meanings:
- ok: contract is consistent with the rule
- deviation: contract contains a clause that contradicts the rule
- missing: the document does not address this topic at all
"""

REVIEW_USER = """\
Document: {filename}
Playbook rule: {rule}

Relevant passages:
{passages}
"""


async def _review_one(doc_id: str, filename: str, rule: str) -> dict:
    chunks = retrieve_chunks(query=rule, doc_ids=[doc_id], n=5)

    if not chunks:
        return {
            "doc_id": doc_id,
            "filename": filename,
            "rule": rule,
            "status": "missing",
            "explanation": "No relevant passages found in this document.",
            "quote": None,
            "page": None,
            "location_hint": None,
        }

    passages = "\n\n---\n\n".join(
        f"[Page {c['page']}]\n{c['text']}" for c in chunks
    )

    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": REVIEW_USER.format(
                    filename=filename, rule=rule, passages=passages
                )},
            ],
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    elif LLM_PROVIDER == "ollama":
        raw = await _ollama_chat_json(
            system=REVIEW_SYSTEM,
            user=REVIEW_USER.format(filename=filename, rule=rule, passages=passages),
        ) or _local_review(rule=rule, chunks=chunks)
    elif gemini_client:
        raw = await _gemini_chat_json(
            system=REVIEW_SYSTEM,
            user=REVIEW_USER.format(filename=filename, rule=rule, passages=passages),
        ) or _local_review(rule=rule, chunks=chunks)
    else:
        raw = _local_review(rule=rule, chunks=chunks)

    best_page = chunks[0]["page"] if chunks else None

    return {
        "doc_id": doc_id,
        "filename": filename,
        "rule": rule,
        "status": raw.get("status", "missing"),
        "explanation": raw.get("explanation"),
        "quote": raw.get("quote"),
        "page": best_page,
        "location_hint": raw.get("location_hint"),
    }


def _local_review(rule: str, chunks: list[dict]) -> dict:
    keywords = [k for k in re.findall(r"\w+", rule.lower()) if len(k) >= 4]
    best_chunk = chunks[0] if chunks else None
    if not best_chunk:
        return {
            "status": "missing",
            "explanation": "No relevant passages found in this document.",
            "quote": None,
            "location_hint": None,
        }

    text_l = best_chunk["text"].lower()
    overlap = sum(1 for k in keywords if k in text_l)
    ratio = overlap / max(1, len(keywords))

    if ratio >= 0.5:
        status = "ok"
        explanation = "Likely compliant based on strong keyword overlap in retrieved passage."
    elif ratio >= 0.2:
        status = "deviation"
        explanation = "Potential deviation: rule terms are only partially reflected in the passage."
    else:
        status = "missing"
        explanation = "Rule topic is not clearly addressed in retrieved passages."

    quote = re.sub(r"\s+", " ", best_chunk["text"]).strip()[:180] or None
    return {
        "status": status,
        "explanation": explanation,
        "quote": quote,
        "location_hint": f"page {best_chunk['page']}",
    }


async def _ollama_chat_json(system: str, user: str) -> dict | None:
    try:
        timeout = httpx.Timeout(connect=10.0, read=OLLAMA_CHAT_TIMEOUT, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
            return json.loads(content)
    except Exception:
        logger.exception(
            "Ollama review JSON failed (base_url=%s, model=%s)",
            OLLAMA_BASE_URL,
            OLLAMA_CHAT_MODEL,
        )
        return None


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def _gemini_chat_json(system: str, user: str) -> dict | None:
    if not gemini_client:
        return None
    prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"

    def _call() -> str:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": 0,
                "response_mime_type": "application/json",
            },
        )
        return (getattr(resp, "text", None) or "").strip()

    try:
        text = await asyncio.to_thread(_call)
        return _extract_json_object(text)
    except Exception:
        logger.exception("Gemini review JSON failed (model=%s)", GEMINI_MODEL)
        return None


async def run_review(rules: list[str], doc_ids: Optional[list[str]] = None) -> dict:
    """
    Returns:
    {
      "rules": [...],
      "findings": [
        {
          "doc_id", "filename", "rule",
          "status": "ok"|"deviation"|"missing",
          "explanation", "quote", "page", "location_hint"
        },
        ...
      ],
      "summary": {"ok": N, "deviation": N, "missing": N}
    }
    """
    docs = list_documents()
    if doc_ids:
        docs = [d for d in docs if d["id"] in doc_ids]

    logger.info(
        "Review request: llm_mode=%s docs=%s rules=%s max_concurrency=%s",
        _llm_mode(),
        len(docs),
        len(rules),
        REVIEW_MAX_CONCURRENCY,
    )

    semaphore = asyncio.Semaphore(max(1, REVIEW_MAX_CONCURRENCY))
    pairs = [
        (doc["id"], doc["filename"], rule)
        for doc in docs
        for rule in rules
    ]
    total = len(pairs)
    started_at = time.perf_counter()

    async def _bounded_review(pair: tuple[str, str, str]) -> dict:
        doc_id, filename, rule = pair
        async with semaphore:
            return await _review_one(doc_id, filename, rule)

    tasks = [asyncio.create_task(_bounded_review(pair)) for pair in pairs]
    findings: list[dict] = []
    completed = 0
    progress_every = max(1, min(10, total // 5 if total > 0 else 1))

    for task in asyncio.as_completed(tasks):
        findings.append(await task)
        completed += 1
        if completed % progress_every == 0 or completed == total:
            elapsed = time.perf_counter() - started_at
            logger.info("Review progress: %s/%s completed (%.1fs)", completed, total, elapsed)

    summary = {"ok": 0, "deviation": 0, "missing": 0}
    for f in findings:
        summary[f["status"]] = summary.get(f["status"], 0) + 1

    return {
        "rules": rules,
        "findings": list(findings),
        "summary": summary,
    }
