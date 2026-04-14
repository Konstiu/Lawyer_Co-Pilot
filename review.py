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
from typing import Optional

import httpx
from openai import AsyncOpenAI
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
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")

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

    tasks = [
        _review_one(doc["id"], doc["filename"], rule)
        for doc in docs
        for rule in rules
    ]
    findings = await asyncio.gather(*tasks)

    summary = {"ok": 0, "deviation": 0, "missing": 0}
    for f in findings:
        summary[f["status"]] = summary.get(f["status"], 0) + 1

    return {
        "rules": rules,
        "findings": list(findings),
        "summary": summary,
    }
