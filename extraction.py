"""
Extraction pipeline
────────────────────
For each (document × field) pair:
  1. Retrieve top-k chunks most relevant to the field
  2. Ask the LLM to extract the value (or flag absence)
  3. Return structured rows with source citations
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

try:
    from .llm_client import (
        openai_chat_client as client,
        gemini_client,
        OPENAI_MODEL,
        LLM_PROVIDER,
        llm_mode,
        resolve_chunk_for_quote,
        ollama_chat_json,
        gemini_chat_json,
    )
    from .ingestion import list_documents, retrieve_chunks
except ImportError:
    from llm_client import (
        openai_chat_client as client,
        gemini_client,
        OPENAI_MODEL,
        LLM_PROVIDER,
        llm_mode,
        resolve_chunk_for_quote,
        ollama_chat_json,
        gemini_chat_json,
    )
    from ingestion import list_documents, retrieve_chunks

EXTRACT_MAX_CONCURRENCY = int(os.getenv("EXTRACT_MAX_CONCURRENCY", "6"))
logger = logging.getLogger("legal_copilot")

EXTRACT_SYSTEM = """\
You are a precise legal analyst. You will receive text passages from a legal document
and must extract a specific piece of information.

Respond ONLY with a JSON object — no prose, no markdown fences.
Schema:
{
  "value": "<extracted value as a short string, or null>",
  "status": "found" | "not_specified" | "uncertain",
  "quote": "<verbatim short quote from the passage, ≤30 words, that supports the value — or null>",
  "location_hint": "<e.g. 'clause 12.2' or 'paragraph 3' if discernible — or null>"
}

Status meanings:
- found: the information is clearly present
- not_specified: the document clearly does not address this
- uncertain: passages are ambiguous or only partially relevant
"""

EXTRACT_USER = """\
Document: {filename}
Field to extract: {field}

Relevant passages:
{passages}
"""


async def _extract_one(
    doc_id: str, filename: str, field: str, corpus: str | None = "user_docs"
) -> dict:
    chunks = await asyncio.to_thread(
        retrieve_chunks, query=field, doc_ids=[doc_id], n=5, corpus=corpus
    )
    if not chunks:
        return {
            "doc_id": doc_id,
            "filename": filename,
            "field": field,
            "value": None,
            "status": "not_specified",
            "quote": None,
            "page": None,
            "location_hint": None,
            "source_anchor": None,
        }

    passages = "\n\n---\n\n".join(f"[Page {c['page']}]\n{c['text']}" for c in chunks)
    user_msg = EXTRACT_USER.format(filename=filename, field=field, passages=passages)

    raw: dict | None = None
    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    elif LLM_PROVIDER == "ollama":
        raw = await ollama_chat_json(system=EXTRACT_SYSTEM, user=user_msg)
    elif gemini_client:
        raw = await gemini_chat_json(system=EXTRACT_SYSTEM, user=user_msg)

    if not raw:
        raw = _local_extract(field=field, chunks=chunks)

    best = resolve_chunk_for_quote(chunks, raw.get("quote")) or (chunks[0] if chunks else None)
    source_anchor = (
        {
            "doc_id": best["doc_id"],
            "filename": best["filename"],
            "chunk_id": best.get("chunk_id"),
            "chunk_index": best.get("chunk_index"),
            "page": best.get("page"),
            "page_start": best.get("page_start"),
            "page_end": best.get("page_end"),
            "char_start": best.get("char_start"),
            "char_end": best.get("char_end"),
        }
        if best
        else None
    )

    return {
        "doc_id": doc_id,
        "filename": filename,
        "field": field,
        "value": raw.get("value"),
        "status": raw.get("status", "uncertain"),
        "quote": raw.get("quote"),
        "page": best["page"] if best else None,
        "location_hint": raw.get("location_hint"),
        "source_anchor": source_anchor,
    }


def _local_extract(field: str, chunks: list[dict]) -> dict:
    keywords = [k for k in re.findall(r"\w+", field.lower()) if len(k) >= 4]
    best_sentence = None
    best_score = -1
    best_page = None

    for c in chunks:
        for sent in re.split(r"(?<=[.!?])\s+", c["text"]):
            sent_l = sent.lower()
            score = sum(1 for k in keywords if k in sent_l)
            if score > best_score and len(sent.strip()) > 20:
                best_score = score
                best_sentence = sent.strip()
                best_page = c["page"]

    if not best_sentence or best_score <= 0:
        return {"value": None, "status": "not_specified", "quote": None, "location_hint": None}

    return {
        "value": best_sentence[:180],
        "status": "found" if best_score >= max(1, len(keywords) // 2) else "uncertain",
        "quote": best_sentence[:180],
        "location_hint": f"page {best_page}" if best_page else None,
    }


async def run_extraction(
    fields: list[str],
    doc_ids: Optional[list[str]] = None,
    corpus: str | None = "user_docs",
) -> dict:
    docs = list_documents(corpus=corpus)
    if doc_ids:
        docs = [d for d in docs if d["id"] in doc_ids]

    logger.info(
        "Extraction: llm_mode=%s docs=%s fields=%s concurrency=%s",
        llm_mode(), len(docs), len(fields), EXTRACT_MAX_CONCURRENCY,
    )

    semaphore = asyncio.Semaphore(max(1, EXTRACT_MAX_CONCURRENCY))
    pairs = [(doc["id"], doc["filename"], field) for doc in docs for field in fields]
    total = len(pairs)
    started_at = time.perf_counter()

    async def _bounded(pair: tuple[str, str, str]) -> dict:
        doc_id, filename, field = pair
        async with semaphore:
            return await _extract_one(doc_id, filename, field, corpus=corpus)

    tasks = [asyncio.create_task(_bounded(p)) for p in pairs]
    results: list[dict] = []
    completed = 0
    progress_every = max(1, min(10, total // 5 if total > 0 else 1))

    for task in asyncio.as_completed(tasks):
        results.append(await task)
        completed += 1
        if completed % progress_every == 0 or completed == total:
            logger.info(
                "Extraction progress: %s/%s (%.1fs)",
                completed, total, time.perf_counter() - started_at,
            )

    rows_map: dict[str, dict] = {}
    for r in results:
        key = r["doc_id"]
        if key not in rows_map:
            rows_map[key] = {"doc_id": r["doc_id"], "filename": r["filename"], "cells": {}}
        rows_map[key]["cells"][r["field"]] = {
            "value": r["value"],
            "status": r["status"],
            "quote": r["quote"],
            "page": r["page"],
            "location_hint": r["location_hint"],
            "source_anchor": r.get("source_anchor"),
        }

    return {"fields": fields, "rows": list(rows_map.values())}
