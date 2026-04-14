"""
Legal Co-Pilot — Backend
Run: uvicorn backend.main:app --reload
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import logging

try:
    from .ingestion import ingest_document, list_documents
    from .extraction import run_extraction
    from .review import run_review
    from .qa import run_qa
except ImportError:
    from ingestion import ingest_document, list_documents
    from extraction import run_extraction
    from review import run_review
    from qa import run_qa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="Legal Co-Pilot")
logger = logging.getLogger("legal_copilot")


def _internal_error(op: str) -> HTTPException:
    logger.error("API error in %s", op, exc_info=False)
    return HTTPException(status_code=500, detail="Internal server error. Check server logs.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve frontend ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
candidate_frontend = os.path.join(BASE_DIR, "..", "frontend")
FRONTEND_DIR = candidate_frontend if os.path.isdir(candidate_frontend) else BASE_DIR

static_dir = os.path.join(FRONTEND_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ── Documents ───────────────────────────────────────────────────────────────
@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and ingest a PDF or text document."""
    try:
        content = await file.read()
        result = ingest_document(filename=file.filename, content=content)
        return result
    except Exception:
        raise _internal_error("upload_document")

@app.get("/api/documents")
async def get_documents():
    """List all ingested documents."""
    try:
        return list_documents()
    except Exception:
        raise _internal_error("get_documents")

@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    try:
        try:
            from .ingestion import delete_document as _del
        except ImportError:
            from ingestion import delete_document as _del
        return _del(doc_id)
    except Exception:
        raise _internal_error("delete_document")


# ── Extraction ───────────────────────────────────────────────────────────────
class ExtractionRequest(BaseModel):
    fields: list[str]           # e.g. ["notice period", "governing law"]
    doc_ids: Optional[list[str]] = None  # None = all documents

@app.post("/api/extract")
async def extract(req: ExtractionRequest):
    """Extract structured fields from documents. Returns a table."""
    try:
        return await run_extraction(fields=req.fields, doc_ids=req.doc_ids)
    except Exception:
        raise _internal_error("extract")


# ── Review ───────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    rules: list[str]            # e.g. ["governing law must be Germany"]
    doc_ids: Optional[list[str]] = None

@app.post("/api/review")
async def review(req: ReviewRequest):
    """Check documents against a playbook. Returns flagged deviations."""
    try:
        return await run_review(rules=req.rules, doc_ids=req.doc_ids)
    except Exception:
        raise _internal_error("review")


# ── Q&A ──────────────────────────────────────────────────────────────────────
class QARequest(BaseModel):
    question: str
    doc_ids: Optional[list[str]] = None
    history: Optional[list[dict]] = None  # [{role, content}, ...]

@app.post("/api/qa")
async def qa(req: QARequest):
    """Answer a question across documents with source citations."""
    try:
        return await run_qa(
            question=req.question,
            doc_ids=req.doc_ids,
            history=req.history or []
        )
    except Exception:
        raise _internal_error("qa")
