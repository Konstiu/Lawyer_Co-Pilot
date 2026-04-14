# Legal Co-Pilot

A small-scale Harvey/Legora — upload contracts, extract structured data,
run playbook reviews, and ask questions with exact source citations.

---

## Architecture

```
legal-copilot/
├── backend/
│   ├── main.py          ← FastAPI app + all routes
│   ├── ingestion.py     ← PDF parsing, chunking, embedding, ChromaDB + SQLite
│   ├── extraction.py    ← Field extraction pipeline (doc × field → table)
│   ├── review.py        ← Playbook rule checker (doc × rule → ok/deviation/missing)
│   └── qa.py            ← Multi-document Q&A with citations
├── frontend/
│   └── index.html       ← Single-file UI (served by FastAPI)
├── data/                ← Created automatically
│   ├── chroma/          ← ChromaDB vector store
│   └── documents.db     ← SQLite (doc metadata + raw chunks)
├── requirements.txt
└── README.md
```

### Data flow

```
Upload PDF
  └─→ ingestion.py
        ├─ extract text (pymupdf)
        ├─ chunk with overlap + page tracking
        ├─ embed (OpenAI text-embedding-3-small)
        ├─ store vectors → ChromaDB
        └─ store metadata → SQLite

Run Extraction / Review / Q&A
  └─→ retrieve_chunks()   ← semantic search in ChromaDB
        └─→ LLM (gpt-4o)  ← structured JSON response
              └─→ response with value + quote + page + location_hint
```

---

## Setup

### 1. Clone / create project

```bash
cd legal-copilot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Choose model backend

#### OpenAI mode (optional)

```bash
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."
```

#### Ollama mode (local)

```bash
export LLM_PROVIDER="ollama"
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_CHAT_MODEL="llama3.1:8b"
export OLLAMA_EMBED_MODEL="nomic-embed-text"
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

Or create a `.env` file and load with `python-dotenv`.

If you do not set `OPENAI_API_KEY`:
- with `LLM_PROVIDER=ollama`, the app uses local Ollama models
- otherwise it runs in a heuristic fallback mode (no external API)

This keeps the app usable for demos/offline testing, but output quality is lower than
with OpenAI models.
If you switch between modes on an existing index and see embedding-dimension errors,
delete `./data/chroma` and re-ingest documents.

### 3. Start the server

```bash
uvicorn backend.main:app --reload --port 8000
```

### 4. Open the UI

```
http://localhost:8000
```

---

## Usage

### Upload documents
Click **+ Upload document** in the sidebar. Supports PDF and plain text.
Documents are chunked, embedded, and indexed automatically.

### Extraction
1. Click **Extraction** in the sidebar
2. Enter fields one per line (e.g. `Notice period`, `Governing law`)
3. Click **Run ↗**
4. Every cell shows the extracted value, status badge, and a clickable
   source reference (clause + page number)

Status badges:
- `found` — clearly present in the document
- `not_specified` — document clearly does not address this
- `uncertain` — ambiguous or incomplete evidence

### Rule Review
1. Click **Rule Review**
2. Enter rules one per line (e.g. `Governing law must be Germany`)
3. Click **Run ↗**
4. Each rule × document is checked and flagged:
   - `ok` — compliant
   - `deviation` — contradicts the rule
   - `missing` — document doesn't address the topic

### Q&A
1. Click **Q&A**
2. Ask a question (e.g. *In which contracts can the landlord terminate without cause?*)
3. Answer is synthesized across all documents with clickable source chips

---

## Configuration

Set via environment variables:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `ollama`, or fallback without remote model |
| `OPENAI_API_KEY` | — | Optional. If missing, local fallback mode is used |
| `OPENAI_MODEL` | `gpt-4o` | Chat model for OpenAI mode |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | Ollama chat model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `DATA_DIR` | `./data` | Where ChromaDB + SQLite are stored |
| `CHUNK_SIZE` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between chunks |
| `EMBED_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `LOCAL_EMBED_DIM` | `1536` | Embedding dimension for local fallback mode |

---

## Core challenges addressed

| Challenge | Implementation |
|---|---|
| **Source grounding** | Each chunk stores `page`, `char_start/end`; LLM is prompted to return `location_hint` + verbatim `quote` |
| **Handling absence** | Three-way status: `found` / `not_specified` / `uncertain` — LLM is explicitly instructed on the difference |
| **Rule-based review** | Per-rule retrieval + structured `ok/deviation/missing` JSON schema with explanation |
| **Multi-doc extraction** | Async `asyncio.gather` — all (doc × field) pairs run concurrently |

---

## Next steps

- [ ] Streaming responses for Q&A
- [ ] PDF viewer with highlighted passages (PDF.js)
- [ ] Export table as CSV / Excel
- [ ] Document selection (run only on subset)
- [ ] Caching: skip re-extraction for unchanged docs
