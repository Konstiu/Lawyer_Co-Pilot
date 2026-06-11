"""
Rule review (playbook linter)
──────────────────────────────
For each (document × rule) pair:
  1. Retrieve chunks most relevant to the rule
  2. Ask the LLM to evaluate compliance
  3. Return ok / deviation / missing with explanation + citation
"""

from .config import load_environment

load_environment()

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

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

REVIEW_MAX_CONCURRENCY = int(os.getenv("REVIEW_MAX_CONCURRENCY", "6"))
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


async def _review_one(
    doc_id: str, filename: str, rule: str, corpus: str | None = "user_docs"
) -> dict:
    chunks = await asyncio.to_thread(
        retrieve_chunks, query=rule, doc_ids=[doc_id], n=5, corpus=corpus
    )

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
            "source_anchor": None,
        }

    passages = "\n\n---\n\n".join(f"[Page {c['page']}]\n{c['text']}" for c in chunks)
    user_msg = REVIEW_USER.format(filename=filename, rule=rule, passages=passages)

    raw: dict | None = None
    if client:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    elif LLM_PROVIDER == "ollama":
        raw = await ollama_chat_json(system=REVIEW_SYSTEM, user=user_msg)
    elif gemini_client:
        raw = await gemini_chat_json(system=REVIEW_SYSTEM, user=user_msg)

    if not raw:
        raw = _local_review(rule=rule, chunks=chunks)

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
        "rule": rule,
        "status": raw.get("status", "missing"),
        "explanation": raw.get("explanation"),
        "quote": raw.get("quote"),
        "page": best["page"] if best else None,
        "location_hint": raw.get("location_hint"),
        "source_anchor": source_anchor,
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


async def run_review(
    rules: list[str],
    doc_ids: Optional[list[str]] = None,
    corpus: str | None = "user_docs",
) -> dict:
    docs = list_documents(corpus=corpus)
    if doc_ids:
        docs = [d for d in docs if d["id"] in doc_ids]

    logger.info(
        "Review: llm_mode=%s docs=%s rules=%s concurrency=%s",
        llm_mode(), len(docs), len(rules), REVIEW_MAX_CONCURRENCY,
    )

    semaphore = asyncio.Semaphore(max(1, REVIEW_MAX_CONCURRENCY))
    pairs = [(doc["id"], doc["filename"], rule) for doc in docs for rule in rules]
    total = len(pairs)
    started_at = time.perf_counter()

    async def _bounded(pair: tuple[str, str, str]) -> dict:
        doc_id, filename, rule = pair
        async with semaphore:
            return await _review_one(doc_id, filename, rule, corpus=corpus)

    tasks = [asyncio.create_task(_bounded(p)) for p in pairs]
    findings: list[dict] = []
    completed = 0
    progress_every = max(1, min(10, total // 5 if total > 0 else 1))

    for task in asyncio.as_completed(tasks):
        findings.append(await task)
        completed += 1
        if completed % progress_every == 0 or completed == total:
            logger.info(
                "Review progress: %s/%s (%.1fs)",
                completed, total, time.perf_counter() - started_at,
            )

    summary: dict[str, int] = {"ok": 0, "deviation": 0, "missing": 0}
    for f in findings:
        status = f["status"]
        summary[status] = summary.get(status, 0) + 1

    return {"rules": rules, "findings": findings, "summary": summary}
