"""
Ingestion pipeline
──────────────────
1. Parse PDF / text → raw text + page mapping
2. Chunk into overlapping windows (with page numbers preserved)
3. Embed chunks via OpenAI
4. Store in ChromaDB (vector) + SQLite (metadata/raw text)
"""

import hashlib
import io
import math
import os
import re
import sqlite3
import logging
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import chromadb
import httpx
from openai import OpenAI
from chromadb.config import Settings
from chromadb.errors import InvalidDimensionException

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(exist_ok=True)

CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", 1500))     # characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))
MIN_CHUNK_CHARS = int(os.getenv("MIN_CHUNK_CHARS", 80))
EMBED_MODEL   = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_BATCH_SIZE = max(1, int(os.getenv("EMBED_BATCH_SIZE", 64)))
EMBED_MAX_RETRIES = max(1, int(os.getenv("EMBED_MAX_RETRIES", 3)))
EMBED_RETRY_BASE_SECONDS = float(os.getenv("EMBED_RETRY_BASE_SECONDS", 1.0))
LOCAL_EMBED_DIM = int(os.getenv("LOCAL_EMBED_DIM", "1536"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")
_EMBED_MODE_LOGGED = False

chroma = chromadb.PersistentClient(
    path=str(DATA_DIR / "chroma"),
    settings=Settings(anonymized_telemetry=False),
)
collection = chroma.get_or_create_collection(
    name="legal_docs",
    metadata={"hnsw:space": "cosine"},
)

DB_PATH = DATA_DIR / "documents.db"


# ── SQLite helpers ───────────────────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT,
            page_count INTEGER,
            chunk_count INTEGER,
            ingested_at TEXT,
            full_text TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT,
            page_num INTEGER,
            char_start INTEGER,
            char_end INTEGER,
            text TEXT
        )
    """)
    conn.commit()
    return conn


# ── Text extraction ──────────────────────────────────────────────────────────
def _normalize_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+$", "", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _extract_docx_text(content: bytes) -> str:
    """
    Extract text from DOCX using stdlib only.
    """
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml_data = zf.read("word/document.xml")
    root = ET.fromstring(xml_data)
    paragraphs: list[str] = []
    for p in root.findall(".//w:p", ns):
        texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return _normalize_text("\n\n".join(paragraphs))


def _extract_text(filename: str, content: bytes) -> list[dict]:
    """
    Returns list of {page: int, text: str}.
    Handles PDF via pymupdf, plain text as single page.
    """
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []
        for i, page in enumerate(doc, 1):
            pages.append({"page": i, "text": _normalize_text(page.get_text())})
        return pages
    if lower_name.endswith(".docx"):
        return [{"page": 1, "text": _extract_docx_text(content)}]
    # Plain text / markdown
    text = content.decode("utf-8", errors="replace")
    return [{"page": 1, "text": _normalize_text(text)}]


# ── Chunking ─────────────────────────────────────────────────────────────────
def _chunk_pages(pages: list[dict]) -> list[dict]:
    """
    Sliding-window chunker that preserves page numbers.
    Each chunk: {chunk_id_suffix, page, char_start, char_end, text}
    """
    if not pages:
        return []

    safe_chunk_size = max(200, CHUNK_SIZE)
    safe_overlap = min(max(0, CHUNK_OVERLAP), safe_chunk_size - 50)
    paragraph_splitter = re.compile(r"\n\s*\n")

    segments: list[dict[str, Any]] = []
    cursor = 0
    for page in pages:
        page_text = _normalize_text(page["text"])
        if not page_text:
            continue
        paragraphs = [p.strip() for p in paragraph_splitter.split(page_text) if p.strip()]
        if not paragraphs:
            paragraphs = [page_text]
        for para in paragraphs:
            start = cursor
            end = start + len(para)
            segments.append({"text": para, "page": page["page"], "char_start": start, "char_end": end})
            cursor = end + 2  # account for separator between paragraphs

    if not segments:
        return []

    chunks: list[dict[str, Any]] = []
    start_idx = 0
    while start_idx < len(segments):
        end_idx = start_idx
        size = 0
        while end_idx < len(segments) and (size < safe_chunk_size or end_idx == start_idx):
            size += len(segments[end_idx]["text"]) + 2
            end_idx += 1

        window = segments[start_idx:end_idx]
        if not window:
            break

        page_weight: dict[int, int] = {}
        for seg in window:
            pg = int(seg["page"])
            page_weight[pg] = page_weight.get(pg, 0) + len(seg["text"])
        dominant_page = max(page_weight, key=page_weight.get)
        text = "\n\n".join(seg["text"] for seg in window).strip()

        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append(
                {
                    "text": text,
                    "page": dominant_page,
                    "char_start": window[0]["char_start"],
                    "char_end": window[-1]["char_end"],
                }
            )

        if end_idx >= len(segments):
            break

        if safe_overlap == 0:
            next_start = end_idx
        else:
            overlap_chars = 0
            next_start = end_idx
            while next_start > start_idx and overlap_chars < safe_overlap:
                next_start -= 1
                overlap_chars += len(segments[next_start]["text"]) + 2

        if next_start <= start_idx:
            next_start = start_idx + 1
        start_idx = next_start

    return chunks


# ── Embeddings ────────────────────────────────────────────────────────────────
def _embed(texts: list[str]) -> list[list[float]]:
    global _EMBED_MODE_LOGGED
    if not _EMBED_MODE_LOGGED:
        if client:
            logger.info("Embedding backend: openai (model=%s)", EMBED_MODEL)
        elif LLM_PROVIDER == "ollama":
            logger.info("Embedding backend: ollama (model=%s)", OLLAMA_EMBED_MODEL)
        else:
            logger.info("Embedding backend: local_fallback (dim=%s)", LOCAL_EMBED_DIM)
        _EMBED_MODE_LOGGED = True

    if not texts:
        return []
    if client:
        for attempt in range(1, EMBED_MAX_RETRIES + 1):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
                return [d.embedding for d in resp.data]
            except Exception as exc:
                if attempt >= EMBED_MAX_RETRIES:
                    raise
                sleep_s = EMBED_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "OpenAI embeddings failed (attempt %s/%s): %s; retrying in %.1fs",
                    attempt,
                    EMBED_MAX_RETRIES,
                    type(exc).__name__,
                    sleep_s,
                )
                time.sleep(sleep_s)
    if LLM_PROVIDER == "ollama":
        return [_ollama_embed(t) for t in texts]
    return [_local_embed(t) for t in texts]


def _local_embed(text: str) -> list[float]:
    """
    Key-less deterministic embedding fallback.
    Hashes tokens into a fixed-size vector and L2-normalizes it.
    """
    vec = [0.0] * LOCAL_EMBED_DIM
    tokens = re.findall(r"\w+", (text or "").lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % LOCAL_EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _ollama_embed(text: str) -> list[float]:
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
                timeout=60.0,
            )
            resp.raise_for_status()
            embedding = resp.json().get("embedding")
            if isinstance(embedding, list) and embedding:
                return embedding
        except Exception as exc:
            if attempt >= EMBED_MAX_RETRIES:
                logger.exception(
                    "Ollama embedding failed after %s attempts (base_url=%s, model=%s)",
                    EMBED_MAX_RETRIES,
                    OLLAMA_BASE_URL,
                    OLLAMA_EMBED_MODEL,
                )
                break
            sleep_s = EMBED_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Ollama embedding failed (attempt %s/%s): %s; retrying in %.1fs",
                attempt,
                EMBED_MAX_RETRIES,
                type(exc).__name__,
                sleep_s,
            )
            time.sleep(sleep_s)
    return _local_embed(text)


# ── Public API ────────────────────────────────────────────────────────────────
def ingest_document(filename: str, content: bytes) -> dict[str, Any]:
    started_at = time.perf_counter()
    doc_id = hashlib.sha256(content).hexdigest()[:16]
    db = _get_db()
    try:
        # Idempotent
        existing = db.execute("SELECT id FROM documents WHERE id=?", (doc_id,)).fetchone()
        if existing:
            return {"doc_id": doc_id, "status": "already_exists", "filename": filename}

        pages = _extract_text(filename, content)
        chunks = _chunk_pages(pages)
        full_text = "\n".join(p["text"] for p in pages)
        logger.info(
            "Ingesting document: filename=%s pages=%s chunks=%s chunk_size=%s overlap=%s",
            filename,
            len(pages),
            len(chunks),
            CHUNK_SIZE,
            CHUNK_OVERLAP,
        )

        chunk_texts = [c["text"] for c in chunks]
        embed_started_at = time.perf_counter()
        embeddings: list[list[float]] = []
        for start in range(0, len(chunk_texts), EMBED_BATCH_SIZE):
            batch = chunk_texts[start:start + EMBED_BATCH_SIZE]
            embeddings.extend(_embed(batch))
        embed_ms = int((time.perf_counter() - embed_started_at) * 1000)
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding count mismatch: chunks={len(chunks)} embeddings={len(embeddings)}"
            )

        chroma_ids = [f"{doc_id}__chunk_{i}" for i in range(len(chunks))]
        collection.add(
            ids=chroma_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=[{
                "doc_id": doc_id,
                "filename": filename,
                "page": c["page"],
                "char_start": c["char_start"],
                "char_end": c["char_end"],
            } for c in chunks],
        )

        db.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?)",
            (doc_id, filename, len(pages), len(chunks), datetime.utcnow().isoformat(), full_text)
        )
        db.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
            [
                (chroma_ids[i], doc_id, c["page"], c["char_start"], c["char_end"], c["text"])
                for i, c in enumerate(chunks)
            ],
        )
        db.commit()

        ingest_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Ingested document: filename=%s doc_id=%s chunks=%s embed_ms=%s ingest_ms=%s",
            filename,
            doc_id,
            len(chunks),
            embed_ms,
            ingest_ms,
        )
        return {
            "doc_id": doc_id,
            "status": "ingested",
            "filename": filename,
            "pages": len(pages),
            "chunks": len(chunks),
            "embed_ms": embed_ms,
            "ingest_ms": ingest_ms,
        }
    finally:
        db.close()


def list_documents() -> list[dict]:
    db = _get_db()
    try:
        rows = db.execute(
            "SELECT id, filename, page_count, chunk_count, ingested_at FROM documents ORDER BY ingested_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def delete_document(doc_id: str) -> dict:
    db = _get_db()
    try:
        chunk_ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]
        if chunk_ids:
            collection.delete(ids=chunk_ids)
        db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        db.commit()
        return {"doc_id": doc_id, "status": "deleted"}
    finally:
        db.close()


def retrieve_chunks(query: str, doc_ids: list[str] | None = None, n: int = 8) -> list[dict]:
    """
    Semantic search. Returns top-n chunks with metadata.
    Optionally filtered to specific doc_ids.
    """
    [query_emb] = _embed([query])
    total_indexed = collection.count()
    if total_indexed <= 0:
        logger.info("Retrieve: empty index, no chunks returned")
        return []
    n_results = min(n, total_indexed)
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
    logger.debug(
        "Retrieve: requested=%s effective=%s indexed=%s filter_docs=%s",
        n,
        n_results,
        total_indexed,
        len(doc_ids) if doc_ids else 0,
    )

    try:
        results = collection.query(
            query_embeddings=[query_emb],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except InvalidDimensionException as e:
        # Typical when switching embedding backend/model on an existing Chroma index.
        msg = (
            "Embedding dimension mismatch in Chroma index. "
            "You likely switched embedding provider/model after documents were ingested. "
            "Fix: delete ./data/chroma and re-ingest all documents with one consistent embedding setup."
        )
        raise RuntimeError(msg) from e

    chunks = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text": text,
            "doc_id": meta["doc_id"],
            "filename": meta["filename"],
            "page": meta["page"],
            "score": round(1 - dist, 3),
        })
    return chunks
