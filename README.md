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
        └─→ LLM (OpenAI / Ollama / Gemini)  ← structured JSON response
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

#### Gemini mode (Vertex AI / GCP credits)

```bash
export LLM_PROVIDER="gemini"
export GEMINI_MODEL="gemini-2.5-flash-lite"      # low-cost default
export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="<your-project-id>"
export GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default login
```

### 2.1 Export presets (copy/paste)

Use one preset at a time. The first block is the full Gemini + Vertex setup
used with GCP credits.

```bash
# --- Gemini + Vertex AI (recommended for GCP credits) ---
export LLM_PROVIDER="gemini"
export GEMINI_MODEL="gemini-2.5-flash-lite"
export GEMINI_EMBED_MODEL="text-embedding-004"
export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="appliedgenai-494416"
export GOOGLE_CLOUD_LOCATION="europe-west4"

# --- App/runtime defaults ---
export DATA_DIR="./data"
export CHUNK_SIZE="1500"
export CHUNK_OVERLAP="200"
export MIN_CHUNK_CHARS="80"
export EMBED_BATCH_SIZE="64"
export EMBED_MAX_RETRIES="3"
export EMBED_RETRY_BASE_SECONDS="1.0"
export EXTRACT_MAX_CONCURRENCY="6"
export REVIEW_MAX_CONCURRENCY="6"
export QA_TOP_K="6"
```

Optional overrides for other providers:

```bash
# --- OpenAI override ---
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o"

# --- Ollama override ---
export LLM_PROVIDER="ollama"
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_CHAT_MODEL="llama3.1:8b"
export OLLAMA_EMBED_MODEL="nomic-embed-text"
export OLLAMA_CHAT_TIMEOUT="300"
```

Or create a `.env` file and load with `python-dotenv`.

If provider credentials are missing:
- with `LLM_PROVIDER=ollama`, the app uses local Ollama models
- with `LLM_PROVIDER=gemini`, it falls back to local heuristics
- otherwise it runs in a heuristic fallback mode (no external API)

This keeps the app usable for demos/offline testing, but output quality is lower than
with OpenAI models.
If you switch between modes on an existing index and see embedding-dimension errors,
delete `./data/chroma` and re-ingest documents.

### 3. Start the server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Open the UI

```
http://localhost:8000
```

---

## Usage

### Upload documents
Click **+ Upload document** in the sidebar. Supports PDF, DOCX, and plain text.
Documents are chunked, embedded, and indexed automatically.
By default, UI uploads go to corpus `user_docs`.

### Preload legal knowledge corpus
To ingest statutes/case law/commentary into a separate corpus (`legal_knowledge`):

```bash
python scripts/ingest_legal_corpus.py --url-list data/legal_seed_urls.txt --jurisdiction AT --source-type statute
```

Or ingest from local files:

```bash
python scripts/ingest_legal_corpus.py --input-dir ./seed_laws --jurisdiction AT --source-type statute
```

This keeps user drafts/contracts separated from background legal materials.

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
| `LLM_PROVIDER` | `openai` | `openai`, `ollama`, `gemini`, or fallback without remote model |
| `OPENAI_API_KEY` | — | Optional. If missing, local fallback mode is used |
| `OPENAI_MODEL` | `gpt-4o` | Chat model for OpenAI mode |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Chat model for Gemini mode (cost-efficient default) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` | Use Vertex AI auth/billing (recommended for GCP credits) |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project for Vertex AI Gemini |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex AI region |
| `GEMINI_API_KEY` | — | Optional API-key auth (if not using Vertex AI) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | Ollama chat model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `GEMINI_EMBED_MODEL` | `text-embedding-004` | Embedding model when `LLM_PROVIDER=gemini` |
| `DATA_DIR` | `./data` | Where ChromaDB + SQLite are stored |
| `CHUNK_SIZE` | `1500` | Target characters per chunk |
| `CHUNK_OVERLAP` | `200` | Character overlap between chunks |
| `MIN_CHUNK_CHARS` | `80` | Drop chunks smaller than this size |
| `RETRIEVE_CANDIDATE_MULTIPLIER` | `3` | Fetch more initial vector hits before trimming/expanding |
| `RETRIEVE_EXPAND_NEIGHBORS` | `1` | Include adjacent chunks per hit to preserve clause continuity |
| `EMBED_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBED_BATCH_SIZE` | `64` | Embedding request batch size |
| `EMBED_MAX_RETRIES` | `3` | Retries per embedding API call |
| `EMBED_RETRY_BASE_SECONDS` | `1.0` | Exponential backoff base delay |
| `LOCAL_EMBED_DIM` | `1536` | Embedding dimension for local fallback mode |

---

## Core challenges addressed

| Challenge | Implementation |
|---|---|
| **Source grounding** | Each chunk stores `page`, `char_start/end`; LLM is prompted to return `location_hint` + verbatim `quote` |
| **Context continuity** | Retrieval can expand to neighboring chunks to avoid clause truncation at chunk boundaries |
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

---

## RIS / Austria source note

For Austria, RIS is the correct official starting point:
- Info: https://www.ris.bka.gv.at/UI/Info.aspx
- OGD/Interfaces: https://www.ris.bka.gv.at/UI/Ogd.aspx

RIS OGD guidance explicitly recommends paced access (about 1–2s pauses) and contacting `ris.it@bka.gv.at` before initial mass downloads.
