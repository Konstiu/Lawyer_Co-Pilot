"""
Q&A pipeline
─────────────
1. Retrieve top-k chunks across all (selected) documents
2. Synthesize answer with precise citations
"""

from .config import load_environment

load_environment()

import asyncio
import json
import logging
import os
import re
from typing import Optional

from .llm_client import (
    openai_chat_client as client,
    gemini_client,
    OPENAI_MODEL,
    LLM_PROVIDER,
    llm_mode,
    normalize_for_match,
    resolve_chunk_for_quote,
    ollama_chat_text,
    gemini_chat_text,
)
from .ingestion import list_documents, retrieve_chunks

QA_TOP_K = int(os.getenv("QA_TOP_K", "6"))
logger = logging.getLogger("legal_copilot")

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
    history: list[dict] | None = None,
    corpus: str | None = "user_docs",
) -> dict:
    """
    Returns:
    {
      "answer": "<markdown answer with inline citations>",
      "sources": [{"filename", "page", "location_hint", "quote"}, ...]
    }
    """
    history = history or []
    chunks = await asyncio.to_thread(
        retrieve_chunks, query=question, doc_ids=doc_ids, n=QA_TOP_K, corpus=corpus
    )
    logger.info(
        "Q&A: llm_mode=%s docs_filter=%s history=%s top_k=%s",
        llm_mode(),
        len(doc_ids) if doc_ids else 0,
        len(history),
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
                "source_anchor": _anchor_from_chunk(c),
            }
            for c in chunks[:5]
        ]
        answer_lines = ["No LLM backend is configured. Showing retrieved passages:"]
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
        full_text = await gemini_chat_text(messages)
    elif LLM_PROVIDER == "ollama":
        full_text = await ollama_chat_text(messages)
    else:
        raise RuntimeError("No LLM backend configured")

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

    enriched_sources = _enrich_sources_with_anchors(sources, chunks)
    return {"answer": answer, "sources": enriched_sources}


def _short_quote(text: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _anchor_from_chunk(c: dict) -> dict:
    return {
        "doc_id": c.get("doc_id"),
        "filename": c.get("filename"),
        "chunk_id": c.get("chunk_id"),
        "chunk_index": c.get("chunk_index"),
        "page": c.get("page"),
        "page_start": c.get("page_start"),
        "page_end": c.get("page_end"),
        "char_start": c.get("char_start"),
        "char_end": c.get("char_end"),
    }


def _enrich_sources_with_anchors(sources: list[dict], chunks: list[dict]) -> list[dict]:
    if not sources:
        return []
    by_file_page: dict[tuple[str, int], dict] = {}
    by_file: dict[str, list[dict]] = {}
    for c in chunks:
        key = (str(c.get("filename", "")), int(c.get("page") or 0))
        by_file_page.setdefault(key, c)
        by_file.setdefault(str(c.get("filename", "")), []).append(c)

    out: list[dict] = []
    for s in sources:
        filename = str(s.get("filename", ""))
        page = int(s.get("page") or 0)
        quote = str(s.get("quote", "") or "")
        match = resolve_chunk_for_quote(by_file.get(filename, []), quote)
        if not match:
            match = by_file_page.get((filename, page))
        item = dict(s)
        item["source_anchor"] = _anchor_from_chunk(match) if match else None
        out.append(item)
    return out


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
