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

app = FastAPI(title="Legal Co-Pilot")

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
    content = await file.read()
    result = ingest_document(filename=file.filename, content=content)
    return result

@app.get("/api/documents")
async def get_documents():
    """List all ingested documents."""
    return list_documents()

@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    try:
        from .ingestion import delete_document as _del
    except ImportError:
        from ingestion import delete_document as _del
    return _del(doc_id)


# ── Extraction ───────────────────────────────────────────────────────────────
class ExtractionRequest(BaseModel):
    fields: list[str]           # e.g. ["notice period", "governing law"]
    doc_ids: Optional[list[str]] = None  # None = all documents

@app.post("/api/extract")
async def extract(req: ExtractionRequest):
    """Extract structured fields from documents. Returns a table."""
    return await run_extraction(fields=req.fields, doc_ids=req.doc_ids)


# ── Review ───────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    rules: list[str]            # e.g. ["governing law must be Germany"]
    doc_ids: Optional[list[str]] = None

@app.post("/api/review")
async def review(req: ReviewRequest):
    """Check documents against a playbook. Returns flagged deviations."""
    return await run_review(rules=req.rules, doc_ids=req.doc_ids)


# ── Q&A ──────────────────────────────────────────────────────────────────────
class QARequest(BaseModel):
    question: str
    doc_ids: Optional[list[str]] = None
    history: Optional[list[dict]] = None  # [{role, content}, ...]

@app.post("/api/qa")
async def qa(req: QARequest):
    """Answer a question across documents with source citations."""
    return await run_qa(
        question=req.question,
        doc_ids=req.doc_ids,
        history=req.history or []
    )
