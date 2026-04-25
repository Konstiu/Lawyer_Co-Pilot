"""
Q&A pipeline
─────────────
1. Retrieve top-k chunks across all (selected) documents
2. Synthesize answer with precise citations
3. Stream response back
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() in {"1", "true", "yes", "on"}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
QA_TOP_K = int(os.getenv("QA_TOP_K", "6"))
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

QA_SYSTEM = """\
You are a precise legal research assistant. You receive passages retrieved from a set
of legal documents and must answer the user's question.

Rules:
- Answer only from the provided passages. Do not speculate beyond them.
- Reply in the same language as the user's question.
- Start with a direct answer sentence to exactly what was asked.
- Keep it short by default: max 3 sentences unless the user explicitly asks for detail.
- Do not summarize the full document if the question is narrow (e.g., "What is X?").
- Every claim must be supported by a citation in the format [DOC: filename, p. N, clause X].
- If the answer is not in the passages, say so explicitly.

After your answer, output a JSON block (fenced with ```json ... ```) listing all cited sources:
[
  {"filename": "...", "page": N, "location_hint": "...", "quote": "..."}
]
Use only the minimal set of sources needed (typically 1-3).
"""

QA_USER = """\
Question: {question}

Retrieved passages:
{passages}

Answer mode: {answer_mode}
"""


async def run_qa(
    question: str,
    doc_ids: Optional[list[str]] = None,
    history: list[dict] = [],
) -> dict:
    """
    Returns:
    {
      "answer": "<markdown answer with inline citations>",
      "sources": [{"filename", "page", "location_hint", "quote"}, ...]
    }
    """
    chunks = retrieve_chunks(query=question, doc_ids=doc_ids, n=QA_TOP_K)
    logger.info(
        "Q&A request: llm_mode=%s docs_filter=%s history_messages=%s top_k=%s",
        _llm_mode(),
        len(doc_ids) if doc_ids else 0,
        len(history or []),
        QA_TOP_K,
    )

    if not chunks:
        return {
            "answer": "No relevant passages found across the selected documents.",
            "sources": [],
        }

    passages = "\n\n---\n\n".join(
        f"[{c['filename']}, page {c['page']}]\n{c['text']}" for c in chunks
    )

    if not client and not gemini_client and LLM_PROVIDER != "ollama":
        sources = [
            {
                "filename": c["filename"],
                "page": c["page"],
                "location_hint": "retrieved passage",
                "quote": _short_quote(c["text"]),
            }
            for c in chunks[:5]
        ]
        answer_lines = [
            "OPENAI_API_KEY ist nicht gesetzt, daher läuft Q&A im lokalen Fallback-Modus.",
            "Hier sind die relevantesten Passagen:",
        ]
        for c in chunks[:3]:
            answer_lines.append(
                f"- [DOC: {c['filename']}, p. {c['page']}] {_short_quote(c['text'])}"
            )
        return {"answer": "\n".join(answer_lines), "sources": sources}

    messages = [
        {"role": "system", "content": QA_SYSTEM},
        *history,
        {
            "role": "user",
            "content": QA_USER.format(
                question=question,
                passages=passages,
                answer_mode=_answer_mode(question),
            ),
        },
    ]

    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0,
        )
        full_text: str = resp.choices[0].message.content
    elif gemini_client:
        full_text = await _gemini_chat_text(messages)
    elif LLM_PROVIDER == "ollama":
        full_text = await _ollama_chat_text(messages)
    else:
        raise RuntimeError("No LLM backend configured")

    # Split answer from JSON sources block
    answer = full_text
    sources: list[dict] = []

    if "```json" in full_text:
        parts = full_text.split("```json", 1)
        answer = parts[0].strip()
        json_part = parts[1].split("```")[0].strip()
        try:
            sources = json.loads(json_part)
        except json.JSONDecodeError:
            sources = []

    return {"answer": answer, "sources": sources}


def _short_quote(text: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _answer_mode(question: str) -> str:
    q = (question or "").strip().lower()
    definition_patterns = [
        r"^what is\b",
        r"^what does\b",
        r"^define\b",
        r"^was ist\b",
        r"^wie ist .*definiert\b",
        r"^was gilt als\b",
    ]
    if any(re.search(p, q) for p in definition_patterns):
        return "concise_definition (1-2 sentences, no broad summary)"
    return "concise_general (max 3 sentences unless detail requested)"


async def _ollama_chat_text(messages: list[dict]) -> str:
    try:
        timeout = httpx.Timeout(connect=10.0, read=OLLAMA_CHAT_TIMEOUT, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "stream": False,
                    "messages": messages,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
    except Exception:
        logger.exception(
            "Ollama chat failed (base_url=%s, model=%s)",
            OLLAMA_BASE_URL,
            OLLAMA_CHAT_MODEL,
        )
        raise RuntimeError("Ollama chat failed")


async def _gemini_chat_text(messages: list[dict]) -> str:
    if not gemini_client:
        raise RuntimeError("Gemini client not configured")
    prompt = "\n\n".join(
        f"{m.get('role', 'user').upper()}:\n{m.get('content', '')}" for m in messages
    )

    def _call() -> str:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0},
        )
        return (getattr(resp, "text", None) or "").strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        logger.exception("Gemini chat failed (model=%s)", GEMINI_MODEL)
        raise RuntimeError("Gemini chat failed")
