# Runbook

## 1) Open project

Recommended Python version: `3.11` or `3.12`.

If you only have Python `3.14`, do not use it for the project venv. Use a version manager and run the setup with Python `3.12` instead.

Recommended recovery/setup sequence for a Python-3.14-only system:

```bash
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
```

## 2) First-time setup

```bash
bash scripts/setup_local.sh
```

Then, in each new shell:

```bash
source venv/bin/activate
```

## 3) Start backend

```bash
uvicorn app.main:app --reload --port 8000
```

Or use the `.env`-driven launcher:

```bash
python run_server.py
```

Open UI:

- <http://127.0.0.1:8000>

## 4) Ingest legal corpus (optional, second terminal)

```bash
source venv/bin/activate
python scripts/ingest_legal_corpus.py --url-list data/legal_seed_urls.txt --jurisdiction AT --source-type statute
```

## 5) Verify legal corpus loaded

```bash
curl "http://127.0.0.1:8000/api/documents?corpus=legal_knowledge"
```

## 6) Test Q&A against legal corpus

```bash
curl -X POST "http://localhost:8000/api/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"Was regelt dieses Gesetz?","corpus":"legal_knowledge"}'
```

## 7) Reset index/db (only if embedding mismatch happens)

```bash
rm -rf data/chroma
rm -f data/documents.db
```

Then re-run steps 2, 3, and re-ingest documents.

## 8) Evaluate the system

For a quick baseline check on the bundled sample contracts:

```bash
bash test_docs/scripts/api_smoketest.sh
bash test_docs/scripts/benchmark_capture.sh
python test_docs/scripts/compare_runs.py --output test_runs/model_comparison_report.md
python test_docs/scripts/run_benchmark.py
```

For a harder evaluation flow on larger or converted documents:

```bash
bash test_docs/scripts/pdf_hard_run.sh
# or
bash test_docs/scripts/run_docx_batch.sh
```

Scoring and interpretation are documented in:

- `test_docs/docs/EVALUATION_WORKFLOW.md`
- `test_docs/docs/pdf_eval_scorecard.md`
- `test_docs/templates/eval_result_template.json`
