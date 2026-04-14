"""
Ingestion pipeline
──────────────────
1. Parse PDF / text → raw text + page mapping
2. Chunk into overlapping windows (with page numbers preserved)
3. Embed chunks via OpenAI
4. Store in ChromaDB (vector) + SQLite (metadata/raw text)
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
import httpx
from openai import OpenAI
from chromadb.config import Settings

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(exist_ok=True)

CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", 1500))     # characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))
EMBED_MODEL   = os.getenv("EMBED_MODEL", "text-embedding-3-small")
LOCAL_EMBED_DIM = int(os.getenv("LOCAL_EMBED_DIM", "1536"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")

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
def _extract_text(filename: str, content: bytes) -> list[dict]:
    """
    Returns list of {page: int, text: str}.
    Handles PDF via pymupdf, plain text as single page.
    """
    if filename.lower().endswith(".pdf"):
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []
        for i, page in enumerate(doc, 1):
            pages.append({"page": i, "text": page.get_text()})
        return pages
    else:
        # Plain text / markdown
        text = content.decode("utf-8", errors="replace")
        return [{"page": 1, "text": text}]


# ── Chunking ─────────────────────────────────────────────────────────────────
def _chunk_pages(pages: list[dict]) -> list[dict]:
    """
    Sliding-window chunker that preserves page numbers.
    Each chunk: {chunk_id_suffix, page, char_start, char_end, text}
    """
    # Flatten with page markers
    flat_chars: list[tuple[str, int]] = []  # (char, page_num)
    for p in pages:
        for ch in p["text"]:
            flat_chars.append((ch, p["page"]))

    chunks = []
    i = 0
    while i < len(flat_chars):
        window = flat_chars[i : i + CHUNK_SIZE]
        text = "".join(c for c, _ in window)
        # dominant page = most frequent
        pages_in_window = [pg for _, pg in window]
        page = max(set(pages_in_window), key=pages_in_window.count)
        chunks.append({
            "text": text.strip(),
            "page": page,
            "char_start": i,
            "char_end": i + len(window),
        })
        i += CHUNK_SIZE - CHUNK_OVERLAP

    return [c for c in chunks if len(c["text"]) > 50]  # drop tiny trailing chunks


# ── Embeddings ────────────────────────────────────────────────────────────────
def _embed(texts: list[str]) -> list[list[float]]:
    if client:
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]
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
    except Exception:
        logger.exception(
            "Ollama embedding failed (base_url=%s, model=%s)",
            OLLAMA_BASE_URL,
            OLLAMA_EMBED_MODEL,
        )
    return _local_embed(text)


# ── Public API ────────────────────────────────────────────────────────────────
def ingest_document(filename: str, content: bytes) -> dict[str, Any]:
    doc_id = hashlib.sha256(content).hexdigest()[:16]
    db = _get_db()

    # Idempotent
    existing = db.execute("SELECT id FROM documents WHERE id=?", (doc_id,)).fetchone()
    if existing:
        return {"doc_id": doc_id, "status": "already_exists", "filename": filename}

    pages = _extract_text(filename, content)
    chunks = _chunk_pages(pages)
    full_text = "\n".join(p["text"] for p in pages)

    # Embed in batches of 100
    chunk_texts = [c["text"] for c in chunks]
    embeddings: list[list[float]] = []
    for start in range(0, len(chunk_texts), 100):
        embeddings.extend(_embed(chunk_texts[start:start+100]))

    # Store in Chroma
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

    # Store in SQLite
    db.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?)",
        (doc_id, filename, len(pages), len(chunks),
         datetime.utcnow().isoformat(), full_text)
    )
    for i, c in enumerate(chunks):
        db.execute(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
            (chroma_ids[i], doc_id, c["page"], c["char_start"], c["char_end"], c["text"])
        )
    db.commit()

    return {
        "doc_id": doc_id,
        "status": "ingested",
        "filename": filename,
        "pages": len(pages),
        "chunks": len(chunks),
    }


def list_documents() -> list[dict]:
    db = _get_db()
    rows = db.execute(
        "SELECT id, filename, page_count, chunk_count, ingested_at FROM documents ORDER BY ingested_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: str) -> dict:
    db = _get_db()
    chunk_ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]
    if chunk_ids:
        collection.delete(ids=chunk_ids)
    db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.commit()
    return {"doc_id": doc_id, "status": "deleted"}


def retrieve_chunks(query: str, doc_ids: list[str] | None = None, n: int = 8) -> list[dict]:
    """
    Semantic search. Returns top-n chunks with metadata.
    Optionally filtered to specific doc_ids.
    """
    [query_emb] = _embed([query])
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

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
