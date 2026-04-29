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
try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency
    genai = None
from chromadb.config import Settings
from chromadb.errors import InvalidDimensionException

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(exist_ok=True)

CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", 1500))     # characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))
MIN_CHUNK_CHARS = int(os.getenv("MIN_CHUNK_CHARS", 80))
RETRIEVE_EXPAND_NEIGHBORS = max(0, int(os.getenv("RETRIEVE_EXPAND_NEIGHBORS", 1)))
RETRIEVE_CANDIDATE_MULTIPLIER = max(1, int(os.getenv("RETRIEVE_CANDIDATE_MULTIPLIER", 3)))
EMBED_MODEL   = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_BATCH_SIZE = max(1, int(os.getenv("EMBED_BATCH_SIZE", 64)))
EMBED_MAX_RETRIES = max(1, int(os.getenv("EMBED_MAX_RETRIES", 3)))
EMBED_RETRY_BASE_SECONDS = float(os.getenv("EMBED_RETRY_BASE_SECONDS", 1.0))
LOCAL_EMBED_DIM = int(os.getenv("LOCAL_EMBED_DIM", "1536"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "text-embedding-004")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() in {"1", "true", "yes", "on"}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if (LLM_PROVIDER == "openai" and OPENAI_API_KEY) else None
logger = logging.getLogger("legal_copilot")
_EMBED_MODE_LOGGED = False


def _init_gemini_client():
    if LLM_PROVIDER != "gemini" or genai is None:
        return None
    try:
        if GOOGLE_GENAI_USE_VERTEXAI:
            if not GOOGLE_CLOUD_PROJECT:
                logger.warning("LLM_PROVIDER=gemini but GOOGLE_CLOUD_PROJECT is not set; using local embedding fallback")
                return None
            return genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )
        if GEMINI_API_KEY:
            return genai.Client(api_key=GEMINI_API_KEY)
        logger.warning("LLM_PROVIDER=gemini but no auth configured; using local embedding fallback")
        return None
    except Exception:
        logger.exception("Failed to initialize Gemini embedding client")
        return None


gemini_client = _init_gemini_client()

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
            corpus TEXT,
            source_type TEXT,
            source_url TEXT,
            jurisdiction TEXT,
            effective_from TEXT,
            effective_to TEXT,
            page_count INTEGER,
            chunk_count INTEGER,
            ingested_at TEXT,
            text_char_count INTEGER,
            non_empty_pages INTEGER,
            avg_chars_per_page REAL,
            low_text_warning INTEGER,
            full_text TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT,
            corpus TEXT,
            page_num INTEGER,
            page_start INTEGER,
            page_end INTEGER,
            chunk_index INTEGER,
            char_start INTEGER,
            char_end INTEGER,
            text TEXT
        )
    """)
    # Lightweight migration for existing DBs created before extended provenance columns.
    _ensure_column(conn, "chunks", "page_start", "INTEGER")
    _ensure_column(conn, "chunks", "page_end", "INTEGER")
    _ensure_column(conn, "chunks", "chunk_index", "INTEGER")
    _ensure_column(conn, "documents", "text_char_count", "INTEGER")
    _ensure_column(conn, "documents", "non_empty_pages", "INTEGER")
    _ensure_column(conn, "documents", "avg_chars_per_page", "REAL")
    _ensure_column(conn, "documents", "low_text_warning", "INTEGER")
    _ensure_column(conn, "documents", "corpus", "TEXT")
    _ensure_column(conn, "documents", "source_type", "TEXT")
    _ensure_column(conn, "documents", "source_url", "TEXT")
    _ensure_column(conn, "documents", "jurisdiction", "TEXT")
    _ensure_column(conn, "documents", "effective_from", "TEXT")
    _ensure_column(conn, "documents", "effective_to", "TEXT")
    _ensure_column(conn, "chunks", "corpus", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_ingested_at ON documents(ingested_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_corpus ON documents(corpus)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_page ON chunks(doc_id, page_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_corpus ON chunks(corpus)")
    conn.commit()
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in cols}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


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
    Each chunk keeps global char offsets and page span for exact citations.
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
        page_start = min(int(seg["page"]) for seg in window)
        page_end = max(int(seg["page"]) for seg in window)
        text = "\n\n".join(seg["text"] for seg in window).strip()

        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append(
                {
                    "text": text,
                    "page": dominant_page,
                    "page_start": page_start,
                    "page_end": page_end,
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
        elif gemini_client:
            logger.info("Embedding backend: gemini (model=%s)", GEMINI_EMBED_MODEL)
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
    if gemini_client:
        return _gemini_embed_batch(texts)
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


def _gemini_embed_batch(texts: list[str]) -> list[list[float]]:
    if not gemini_client:
        return [_local_embed(t) for t in texts]

    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = gemini_client.models.embed_content(
                model=GEMINI_EMBED_MODEL,
                contents=texts,
            )
            raw_embeddings = getattr(resp, "embeddings", None)
            if raw_embeddings is None and isinstance(resp, dict):
                raw_embeddings = resp.get("embeddings")

            vectors: list[list[float]] = []
            for item in raw_embeddings or []:
                values = getattr(item, "values", None)
                if values is None and isinstance(item, dict):
                    values = item.get("values")
                if isinstance(values, list) and values:
                    vectors.append(values)

            if len(vectors) == len(texts):
                return vectors
            raise RuntimeError(
                f"Gemini embeddings mismatch: requested={len(texts)} received={len(vectors)}"
            )
        except Exception as exc:
            if attempt >= EMBED_MAX_RETRIES:
                logger.exception(
                    "Gemini embeddings failed after %s attempts (model=%s). Falling back to local embeddings.",
                    EMBED_MAX_RETRIES,
                    GEMINI_EMBED_MODEL,
                )
                return [_local_embed(t) for t in texts]
            sleep_s = EMBED_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Gemini embeddings failed (attempt %s/%s): %s; retrying in %.1fs",
                attempt,
                EMBED_MAX_RETRIES,
                type(exc).__name__,
                sleep_s,
            )
            time.sleep(sleep_s)
    return [_local_embed(t) for t in texts]


# ── Public API ────────────────────────────────────────────────────────────────
def ingest_document(
    filename: str,
    content: bytes,
    corpus: str = "user_docs",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    doc_id = hashlib.sha256(content).hexdigest()[:16]
    metadata = metadata or {}
    db = _get_db()
    try:
        # Idempotent
        existing = db.execute("SELECT id FROM documents WHERE id=?", (doc_id,)).fetchone()
        if existing:
            return {"doc_id": doc_id, "status": "already_exists", "filename": filename}

        pages = _extract_text(filename, content)
        chunks = _chunk_pages(pages)
        full_text = "\n".join(p["text"] for p in pages)
        text_char_count = len(full_text)
        non_empty_pages = sum(1 for p in pages if (p.get("text") or "").strip())
        avg_chars_per_page = (text_char_count / max(1, non_empty_pages)) if non_empty_pages else 0.0
        low_text_warning = int(avg_chars_per_page < 300)
        if not full_text.strip():
            return {
                "doc_id": doc_id,
                "status": "empty_document",
                "filename": filename,
                "pages": len(pages),
                "chunks": 0,
                "quality": {
                    "text_char_count": 0,
                    "non_empty_pages": 0,
                    "avg_chars_per_page": 0.0,
                    "low_text_warning": True,
                },
            }
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
                "corpus": corpus,
                "page": c["page"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
                "chunk_index": i,
                "char_start": c["char_start"],
                "char_end": c["char_end"],
            } for i, c in enumerate(chunks)],
        )

        db.execute(
            """
            INSERT INTO documents
              (id, filename, corpus, source_type, source_url, jurisdiction, effective_from, effective_to, page_count, chunk_count, ingested_at, text_char_count, non_empty_pages, avg_chars_per_page, low_text_warning, full_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id,
                filename,
                corpus,
                metadata.get("source_type"),
                metadata.get("source_url"),
                metadata.get("jurisdiction"),
                metadata.get("effective_from"),
                metadata.get("effective_to"),
                len(pages),
                len(chunks),
                datetime.utcnow().isoformat(),
                text_char_count,
                non_empty_pages,
                avg_chars_per_page,
                low_text_warning,
                full_text,
            ),
        )
        db.executemany(
            """
            INSERT INTO chunks
              (id, doc_id, corpus, page_num, page_start, page_end, chunk_index, char_start, char_end, text)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    chroma_ids[i],
                    doc_id,
                    corpus,
                    c["page"],
                    c["page_start"],
                    c["page_end"],
                    i,
                    c["char_start"],
                    c["char_end"],
                    c["text"],
                )
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
            "corpus": corpus,
            "pages": len(pages),
            "chunks": len(chunks),
            "embed_ms": embed_ms,
            "ingest_ms": ingest_ms,
            "quality": {
                "text_char_count": text_char_count,
                "non_empty_pages": non_empty_pages,
                "avg_chars_per_page": round(avg_chars_per_page, 1),
                "low_text_warning": bool(low_text_warning),
            },
        }
    finally:
        db.close()


def list_documents(corpus: str | None = "user_docs") -> list[dict]:
    db = _get_db()
    try:
        if corpus:
            rows = db.execute(
                """
                SELECT
                  id, filename, corpus, source_type, source_url, jurisdiction, effective_from, effective_to,
                  page_count, chunk_count, ingested_at, text_char_count, non_empty_pages, avg_chars_per_page, low_text_warning
                FROM documents
                WHERE corpus=?
                ORDER BY ingested_at DESC
                """,
                (corpus,),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT
                  id, filename, corpus, source_type, source_url, jurisdiction, effective_from, effective_to,
                  page_count, chunk_count, ingested_at, text_char_count, non_empty_pages, avg_chars_per_page, low_text_warning
                FROM documents
                ORDER BY ingested_at DESC
                """
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


def resolve_source_anchor(doc_id: str, chunk_id: str | None = None) -> dict | None:
    db = _get_db()
    try:
        doc = db.execute(
            """
            SELECT id, filename, corpus, source_type, source_url, jurisdiction, effective_from, effective_to
            FROM documents
            WHERE id=?
            """,
            (doc_id,),
        ).fetchone()
        if not doc:
            return None

        chunk = None
        if chunk_id:
            chunk = db.execute(
                """
                SELECT id, chunk_index, page_num, page_start, page_end, char_start, char_end, text
                FROM chunks
                WHERE id=? AND doc_id=?
                """,
                (chunk_id, doc_id),
            ).fetchone()

        payload = {"document": dict(doc), "chunk": dict(chunk) if chunk else None}

        source_url = doc["source_url"]
        if source_url and chunk and str(source_url).lower().endswith(".pdf"):
            payload["open_url"] = f"{source_url}#page={chunk['page_num']}"
        else:
            payload["open_url"] = source_url

        return payload
    finally:
        db.close()


def _neighbor_chunks(db: sqlite3.Connection, doc_id: str, chunk_index: int, radius: int) -> list[dict]:
    if radius <= 0:
        return []
    rows = db.execute(
        """
        SELECT id, doc_id, page_num, page_start, page_end, chunk_index, char_start, char_end, text
        FROM chunks
        WHERE doc_id = ? AND chunk_index BETWEEN ? AND ?
        ORDER BY chunk_index ASC
        """,
        (doc_id, chunk_index - radius, chunk_index + radius),
    ).fetchall()
    return [dict(r) for r in rows]


def retrieve_chunks(
    query: str,
    doc_ids: list[str] | None = None,
    n: int = 8,
    corpus: str | None = "user_docs",
) -> list[dict]:
    """
    Semantic search. Returns top-n chunks with metadata.
    Optionally filtered to specific doc_ids.
    """
    [query_emb] = _embed([query])
    total_indexed = collection.count()
    if total_indexed <= 0:
        logger.info("Retrieve: empty index, no chunks returned")
        return []
    n_results = min(max(n, n * RETRIEVE_CANDIDATE_MULTIPLIER), total_indexed)
    where_clauses: list[dict[str, Any]] = []
    if doc_ids:
        where_clauses.append({"doc_id": {"$in": doc_ids}})
    if corpus:
        where_clauses.append({"corpus": corpus})
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}
    else:
        where = None
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
    seen_ids: set[str] = set()
    for chunk_id, text, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunk = {
            "text": text,
            "doc_id": meta["doc_id"],
            "filename": meta["filename"],
            "chunk_id": chunk_id,
            "chunk_index": meta.get("chunk_index"),
            "page": meta["page"],
            "page_start": meta.get("page_start", meta["page"]),
            "page_end": meta.get("page_end", meta["page"]),
            "char_start": meta.get("char_start"),
            "char_end": meta.get("char_end"),
            "score": round(1 - dist, 3),
        }
        chunks.append(chunk)
        seen_ids.add(chunk_id)
        if len(chunks) >= n:
            break

    if RETRIEVE_EXPAND_NEIGHBORS > 0 and chunks:
        db = _get_db()
        try:
            expanded: list[dict] = []
            for c in chunks:
                expanded.append(c)
                idx = c.get("chunk_index")
                if idx is None:
                    continue
                neighbors = _neighbor_chunks(db, c["doc_id"], int(idx), RETRIEVE_EXPAND_NEIGHBORS)
                for nb in neighbors:
                    nb_id = nb["id"]
                    if nb_id in seen_ids:
                        continue
                    seen_ids.add(nb_id)
                    expanded.append({
                        "text": nb["text"],
                        "doc_id": nb["doc_id"],
                        "filename": c["filename"],
                        "chunk_id": nb_id,
                        "chunk_index": nb.get("chunk_index"),
                        "page": nb["page_num"],
                        "page_start": nb.get("page_start", nb["page_num"]),
                        "page_end": nb.get("page_end", nb["page_num"]),
                        "char_start": nb.get("char_start"),
                        "char_end": nb.get("char_end"),
                        "score": c["score"],
                    })
            chunks = expanded
        finally:
            db.close()

    return chunks
