# Runbook

## 1) Open project

## 2) Load env + venv

```bash
source scripts/dev_env.sh
```

## 3) Start backend

```bash
uvicorn main:app --reload --port 8000
```

Open UI:

- <http://127.0.0.1:8000>

## 4) Ingest legal corpus (optional, second terminal)

```bash
source scripts/dev_env.sh
python scripts/ingest_legal_corpus.py --url-list data/legal_seed_urls.txt --jurisdiction AT --source-type statute
```

## 5) Verify legal corpus loaded

```bash
curl "http:///127.0.0.1:8000/api/documents?corpus=legal_knowledge"
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
