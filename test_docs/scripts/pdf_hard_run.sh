#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
command -v curl >/dev/null || { echo "curl fehlt"; exit 1; }
command -v jq >/dev/null || { echo "jq fehlt"; exit 1; }

echo "Using BASE_URL=$BASE_URL"

echo "[A] Documents currently indexed"
curl -sS "$BASE_URL/api/documents" | jq .

echo "[B] Extraction hard set"
EXTRACT_PAYLOAD="$(jq -Rn --rawfile f test_docs/hard/prompts/pdf_hard_extraction_fields.txt '{fields: ($f | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/extract" \
  -H "Content-Type: application/json" \
  -d "$EXTRACT_PAYLOAD" | jq .

echo "[C] Rule review hard set"
REVIEW_PAYLOAD="$(jq -Rn --rawfile r test_docs/hard/prompts/pdf_hard_review_rules.txt '{rules: ($r | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/review" \
  -H "Content-Type: application/json" \
  -d "$REVIEW_PAYLOAD" | jq .

echo "[D] Q&A hard set"
while IFS= read -r q; do
  [[ -z "$q" ]] && continue
  echo "\nQ: $q"
  QA_PAYLOAD="$(jq -Rn --arg q "$q" '{question: $q}')"
  curl -sS -X POST "$BASE_URL/api/qa" \
    -H "Content-Type: application/json" \
    -d "$QA_PAYLOAD" | jq .
done < test_docs/hard/prompts/pdf_hard_qa_questions.txt

echo "\nDone. Use test_docs/docs/pdf_eval_scorecard.md for grading."
