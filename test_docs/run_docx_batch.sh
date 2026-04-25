#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DOCX_DIR="${DOCX_DIR:-test_docs/files(1)}"
WORK_DIR="${WORK_DIR:-/tmp/legal_copilot_docx_texts}"

command -v curl >/dev/null || { echo "curl fehlt"; exit 1; }
command -v jq >/dev/null || { echo "jq fehlt"; exit 1; }
command -v python >/dev/null || { echo "python fehlt"; exit 1; }

mkdir -p "$WORK_DIR"

echo "Using BASE_URL=$BASE_URL"
echo "Using DOCX_DIR=$DOCX_DIR"
echo "Using WORK_DIR=$WORK_DIR"

# 1) Convert DOCX -> TXT (stdlib only)
python - <<'PY' "$DOCX_DIR" "$WORK_DIR"
import html
import os
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

src = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

files = sorted(src.glob("*.docx"))
if not files:
    raise SystemExit(f"Keine .docx in {src}")

for f in files:
    with zipfile.ZipFile(f) as zf:
        data = zf.read("word/document.xml")
    root = ET.fromstring(data)

    paragraphs = []
    for p in root.findall(".//w:p", ns):
        texts = []
        for t in p.findall(".//w:t", ns):
            if t.text:
                texts.append(t.text)
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)

    txt = "\n\n".join(paragraphs)
    txt = html.unescape(txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip() + "\n"

    out_file = out / (f.stem + ".txt")
    out_file.write_text(txt, encoding="utf-8")
    print(f"converted: {f.name} -> {out_file.name} ({len(txt)} chars)")
PY

# 2) Upload converted TXT files

echo "[1/4] Upload converted documents"
for f in "$WORK_DIR"/*.txt; do
  echo "  -> $f"
  curl -sS -X POST "$BASE_URL/api/documents/upload" -F "file=@$f" | jq .
done

# 3) Quick list

echo "[2/4] List indexed docs"
curl -sS "$BASE_URL/api/documents" | jq .

# 4) Run extraction/review/qa hard sets

echo "[3/4] Extraction hard set"
EXTRACT_PAYLOAD="$(jq -Rn --rawfile f test_docs/pdf_hard_extraction_fields.txt '{fields: ($f | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/extract" \
  -H "Content-Type: application/json" \
  -d "$EXTRACT_PAYLOAD" | jq .

echo "[4/4] Review + Q&A hard set"
REVIEW_PAYLOAD="$(jq -Rn --rawfile r test_docs/pdf_hard_review_rules.txt '{rules: ($r | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/review" \
  -H "Content-Type: application/json" \
  -d "$REVIEW_PAYLOAD" | jq .

while IFS= read -r q; do
  [[ -z "$q" ]] && continue
  echo "\nQ: $q"
  QA_PAYLOAD="$(jq -Rn --arg q "$q" '{question: $q}')"
  curl -sS -X POST "$BASE_URL/api/qa" \
    -H "Content-Type: application/json" \
    -d "$QA_PAYLOAD" | jq .
done < test_docs/pdf_hard_qa_questions.txt

echo "\nDone. Grade with: test_docs/pdf_eval_scorecard.md"
