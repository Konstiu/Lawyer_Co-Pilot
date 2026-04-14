"""
Q&A pipeline
─────────────
1. Retrieve top-k chunks across all (selected) documents
2. Synthesize answer with precise citations
3. Stream response back
"""

import json
import os
import re
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
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None

QA_SYSTEM = """\
You are a precise legal research assistant. You receive passages retrieved from a set
of legal documents and must answer the user's question.

Rules:
- Answer only from the provided passages. Do not speculate beyond them.
- Every claim must be supported by a citation in the format [DOC: filename, p. N, clause X].
- If the answer is not in the passages, say so explicitly.
- If multiple documents have relevant information, synthesize across them.
- Be concise and precise. Lawyers prefer facts over padding.

After your answer, output a JSON block (fenced with ```json ... ```) listing all cited sources:
[
  {"filename": "...", "page": N, "location_hint": "...", "quote": "..."}
]
"""

QA_USER = """\
Question: {question}

Retrieved passages:
{passages}
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
    chunks = retrieve_chunks(query=question, doc_ids=doc_ids, n=12)

    if not chunks:
        return {
            "answer": "No relevant passages found across the selected documents.",
            "sources": [],
        }

    passages = "\n\n---\n\n".join(
        f"[{c['filename']}, page {c['page']}]\n{c['text']}" for c in chunks
    )

    if not client and LLM_PROVIDER != "ollama":
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
        {"role": "user", "content": QA_USER.format(question=question, passages=passages)},
    ]

    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0,
        )
        full_text: str = resp.choices[0].message.content
    else:
        full_text = await _ollama_chat_text(messages)

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


async def _ollama_chat_text(messages: list[dict]) -> str:
    try:
        async with httpx.AsyncClient(timeout=120.0) as http:
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
        return (
            "Ollama ist als Provider gesetzt, aber nicht erreichbar oder das Modell fehlt. "
            "Prüfe `OLLAMA_BASE_URL` und `ollama pull`."
        )
