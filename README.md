# Legal Co-Pilot

A small-scale Harvey/Legora — upload contracts, extract structured data,
run playbook reviews, and ask questions with exact source citations.

---

## Architecture

```
legal-copilot/
├── app/
│   ├── main.py          ← FastAPI app + routes
│   ├── ingestion.py     ← PDF/DOCX/text parsing, chunking, embeddings, ChromaDB + SQLite
│   ├── extraction.py    ← Field extraction pipeline (doc × field → table)
│   ├── review.py        ← Playbook rule checker (doc × rule → ok/deviation/missing)
│   ├── qa.py            ← Multi-document Q&A with citations
│   ├── llm_client.py    ← Provider-agnostic LLM adapter
│   └── config.py        ← Shared `.env` loading
├── frontend/
│   └── index.html       ← Single-file UI served by FastAPI
├── docs/                ← Poster, feedback notes, archived ad-hoc artifacts
├── scripts/             ← Setup and ingestion helpers
├── test_docs/           ← Smoke tests, hard-test prompts, scorecards
├── data/                ← Created automatically
│   ├── chroma/          ← ChromaDB vector store
│   └── documents.db     ← SQLite (doc metadata + raw chunks)
├── run_server.py        ← `.env`-driven server entrypoint
├── requirements.txt
└── README.md
```

### Data flow

```
Upload PDF
  └─→ app/ingestion.py
        ├─ extract text (pymupdf)
        ├─ chunk with overlap + page tracking
        ├─ embed (OpenAI text-embedding-3-small)
        ├─ store vectors → ChromaDB
        └─ store metadata → SQLite

Run Extraction / Review / Q&A
  └─→ app/ingestion.py::retrieve_chunks()   ← semantic search in ChromaDB
        └─→ LLM (OpenAI / Ollama / Gemini)  ← structured JSON response
              └─→ response with value + quote + page + location_hint
```

---

## Setup

### 1. Clone / create project

Recommended Python version: `3.11` or `3.12`.

Do not use Python `3.14` for this project unless you intentionally want to debug native dependency builds. In practice, `pymupdf` may fall back to a local source build instead of using a prebuilt wheel, which is the failure mode most people will hit.

```bash
cd legal-copilot
bash scripts/setup_local.sh
```

This creates `venv/`, installs dependencies, and creates `.env` from `.env.example` if needed.

If your system only has Python `3.14`, use a Python version manager and create the environment with Python `3.12`. `uv` is a good option for this because it can manage Python versions directly.

If you only have Python `3.14`, this is the recommended clean setup:

```bash
cd /home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot
rm -rf venv
rm -rf ~/.cache/pip

curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

uv python install 3.12
uv venv --python 3.12 venv

source venv/bin/activate
python --version
python -m ensurepip --upgrade
python -m pip --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
python run_server.py
```

Important:
- use `python -m pip`, not plain `pip`
- if `No module named pip` appears, run `python -m ensurepip --upgrade`
- verify that `python --version` shows `3.12.x`
- verify that `python -m pip --version` points into the local `venv/`

### 2. Configure `.env`

Edit `.env` with the provider and credentials you want to use.

If you prefer the manual path instead of the bootstrap script:

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### 3. Choose model backend

#### OpenAI mode (optional)

```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="sk-..."
```

#### Ollama mode (local)

```bash
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_CHAT_MODEL="llama3.1:8b"
OLLAMA_EMBED_MODEL="nomic-embed-text"
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

#### Gemini mode (Vertex AI / GCP credits)

```bash
LLM_PROVIDER="gemini"
GEMINI_MODEL="gemini-2.5-flash-lite"      # low-cost default
GOOGLE_GENAI_USE_VERTEXAI="true"
GOOGLE_CLOUD_PROJECT="<your-project-id>"
GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default login
```

### 3.1 `.env` presets

Use one preset at a time. The first block is the full Gemini + Vertex setup
used with GCP credits.

```bash
# --- Gemini + Vertex AI (recommended for GCP credits) ---
LLM_PROVIDER="gemini"
GEMINI_MODEL="gemini-2.5-flash-lite"
GEMINI_EMBED_MODEL="text-embedding-004"
GOOGLE_GENAI_USE_VERTEXAI="true"
GOOGLE_CLOUD_PROJECT="appliedgenai-494416"
GOOGLE_CLOUD_LOCATION="europe-west4"

# --- App/runtime defaults ---
DATA_DIR="./data"
CHUNK_SIZE="1500"
CHUNK_OVERLAP="200"
MIN_CHUNK_CHARS="80"
EMBED_BATCH_SIZE="64"
EMBED_MAX_RETRIES="3"
EMBED_RETRY_BASE_SECONDS="1.0"
EXTRACT_MAX_CONCURRENCY="6"
REVIEW_MAX_CONCURRENCY="6"
QA_TOP_K="6"
```

Optional overrides for other providers:

```bash
# --- OpenAI override ---
LLM_PROVIDER="openai"
OPENAI_API_KEY="sk-..."
OPENAI_MODEL="gpt-4o"

# --- Ollama override ---
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_CHAT_MODEL="llama3.1:8b"
OLLAMA_EMBED_MODEL="nomic-embed-text"
OLLAMA_CHAT_TIMEOUT="300"
```

If provider credentials are missing:
- with `LLM_PROVIDER=ollama`, the app uses local Ollama models
- with `LLM_PROVIDER=gemini`, it falls back to local heuristics
- otherwise it runs in a heuristic fallback mode (no external API)

This keeps the app usable for demos/offline testing, but output quality is lower than
with OpenAI models.
If you switch between modes on an existing index and see embedding-dimension errors,
delete `./data/chroma` and re-ingest documents.

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

Or, if you want a `.env`-driven entrypoint with no manual exports:

```bash
cp .env.example .env
python run_server.py
```

### 5. Open the UI

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

### Evaluation
The repo includes two evaluation levels:

- `test_docs/scripts/api_smoketest.sh` for the bundled baseline sample documents
- `test_docs/scripts/pdf_hard_run.sh` and `test_docs/scripts/run_docx_batch.sh` for harder document sets
- `test_docs/scripts/benchmark_capture.sh` to save one baseline run as structured JSON artifacts plus a summary report
- `test_docs/scripts/compare_runs.py` to turn multiple saved runs into one model-comparison markdown report
- `test_docs/baseline/` contains the small regression dataset and prompts
- `test_docs/hard/` contains the larger document set and harder prompts
- `test_docs/scripts/` contains the runnable evaluation helpers
- `test_docs/docs/` contains expected results and grading guidance

Expected baseline behavior is documented in `test_docs/docs/expected_results.md`.
Scoring guidance is documented in `test_docs/docs/pdf_eval_scorecard.md`.
A single walkthrough that ties these together lives in `test_docs/docs/EVALUATION_WORKFLOW.md`.
Use `test_docs/templates/eval_result_template.json` when recording benchmark or poster-ready results.

If you want one Python command that reads `.env`, starts the app, runs the benchmark, and writes the model-comparison report:

```bash
python test_docs/scripts/run_benchmark.py
```

### Scope and limitations
Current scope is conservative:

- the system is a document-grounded legal assistant, not a source of general legal advice
- legal behavior depends on the uploaded corpus, prompt wording, and rules supplied by the user
- the included legal-knowledge ingestion flow is Austria-oriented by default, but not a validated multi-jurisdiction legal engine

Known limitations:

- absence detection can be unreliable
- layout-heavy PDFs, tables, and nested clauses may lose structure during extraction/chunking
- rule translation from natural language into machine-checkable review criteria is brittle
- evaluation assets are suitable for benchmarking and demos, not for claiming production-grade legal assurance

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
