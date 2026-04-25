"""
Extraction pipeline
────────────────────
For each (document × field) pair:
  1. Retrieve top-k chunks most relevant to the field
  2. Ask Claude to extract the value (or flag absence)
  3. Return structured rows with source citations
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
    from .ingestion import list_documents, retrieve_chunks
except ImportError:
    from ingestion import list_documents, retrieve_chunks

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b")
OLLAMA_CHAT_TIMEOUT = float(os.getenv("OLLAMA_CHAT_TIMEOUT", "300"))
EXTRACT_MAX_CONCURRENCY = int(os.getenv("EXTRACT_MAX_CONCURRENCY", "6"))
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")


def _llm_mode() -> str:
    if client:
        return f"openai:{OPENAI_MODEL}"
    if LLM_PROVIDER == "ollama":
        return f"ollama:{OLLAMA_CHAT_MODEL}"
    return "local_fallback"

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


async def _extract_one(doc_id: str, filename: str, field: str) -> dict:
    chunks = retrieve_chunks(query=field, doc_ids=[doc_id], n=5)
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
        }

    passages = "\n\n---\n\n".join(
        f"[Page {c['page']}]\n{c['text']}" for c in chunks
    )

    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": EXTRACT_USER.format(
                    filename=filename, field=field, passages=passages
                )},
            ],
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    elif LLM_PROVIDER == "ollama":
        raw = await _ollama_chat_json(
            system=EXTRACT_SYSTEM,
            user=EXTRACT_USER.format(filename=filename, field=field, passages=passages),
        ) or _local_extract(field=field, chunks=chunks)
    else:
        raw = _local_extract(field=field, chunks=chunks)

    best_page = chunks[0]["page"] if chunks else None

    return {
        "doc_id": doc_id,
        "filename": filename,
        "field": field,
        "value": raw.get("value"),
        "status": raw.get("status", "uncertain"),
        "quote": raw.get("quote"),
        "page": best_page,
        "location_hint": raw.get("location_hint"),
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
        return {
            "value": None,
            "status": "not_specified",
            "quote": None,
            "location_hint": None,
        }

    return {
        "value": best_sentence[:180],
        "status": "found" if best_score >= max(1, len(keywords) // 2) else "uncertain",
        "quote": best_sentence[:180],
        "location_hint": f"page {best_page}" if best_page else None,
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
            "Ollama extraction JSON failed (base_url=%s, model=%s)",
            OLLAMA_BASE_URL,
            OLLAMA_CHAT_MODEL,
        )
        return None


async def run_extraction(fields: list[str], doc_ids: Optional[list[str]] = None) -> dict:
    """
    Returns:
    {
      "fields": [...],
      "rows": [
        {
          "doc_id": ..., "filename": ...,
          "cells": {
            "notice period": {"value": "30 days", "status": "found", "quote": "...", "page": 8, "location_hint": "§12.2"},
            ...
          }
        }
      ]
    }
    """
    docs = list_documents()
    if doc_ids:
        docs = [d for d in docs if d["id"] in doc_ids]

    logger.info(
        "Extraction request: llm_mode=%s docs=%s fields=%s max_concurrency=%s",
        _llm_mode(),
        len(docs),
        len(fields),
        EXTRACT_MAX_CONCURRENCY,
    )

    # Run all (doc × field) pairs with bounded concurrency and progress logs.
    semaphore = asyncio.Semaphore(max(1, EXTRACT_MAX_CONCURRENCY))
    pairs = [
        (doc["id"], doc["filename"], field)
        for doc in docs
        for field in fields
    ]
    total = len(pairs)
    started_at = time.perf_counter()

    async def _bounded_extract(pair: tuple[str, str, str]) -> dict:
        doc_id, filename, field = pair
        async with semaphore:
            return await _extract_one(doc_id, filename, field)

    tasks = [asyncio.create_task(_bounded_extract(pair)) for pair in pairs]
    results: list[dict] = []
    completed = 0
    progress_every = max(1, min(10, total // 5 if total > 0 else 1))

    for task in asyncio.as_completed(tasks):
        results.append(await task)
        completed += 1
        if completed % progress_every == 0 or completed == total:
            elapsed = time.perf_counter() - started_at
            logger.info("Extraction progress: %s/%s completed (%.1fs)", completed, total, elapsed)

    # Pivot into rows
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
        }

    return {"fields": fields, "rows": list(rows_map.values())}
