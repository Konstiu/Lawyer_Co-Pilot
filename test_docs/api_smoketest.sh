#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

# Requires: curl, jq
command -v curl >/dev/null || {
	echo "curl fehlt"
	exit 1
}
command -v jq >/dev/null || {
	echo "jq fehlt"
	exit 1
}

echo "Using BASE_URL=$BASE_URL"

echo "[1/5] Upload test docs"
for f in test_docs/vertrag_1_saas_msa.txt test_docs/vertrag_2_it_services.txt test_docs/vertrag_3_nda.txt; do
	echo "  -> $f"
	curl -sS -X POST "$BASE_URL/api/documents/upload" \
		-F "file=@$f" >/dev/null
done

echo "[2/5] List docs"
DOCS_JSON="$(curl -sS "$BASE_URL/api/documents")"
echo "$DOCS_JSON" | jq .

echo "[3/5] Run extraction"
EXTRACT_PAYLOAD="$(jq -Rn --rawfile f test_docs/extraction_fields.txt '{fields: ($f | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/extract" \
	-H "Content-Type: application/json" \
	-d "$EXTRACT_PAYLOAD" | jq .

echo "[4/5] Run rule review"
REVIEW_PAYLOAD="$(jq -Rn --rawfile r test_docs/review_rules.txt '{rules: ($r | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/review" \
	-H "Content-Type: application/json" \
	-d "$REVIEW_PAYLOAD" | jq .

echo "[5/5] Run Q&A batch"
while IFS= read -r q; do
	[[ -z "$q" ]] && continue
	echo "\nQ: $q"
	QA_PAYLOAD="$(jq -Rn --arg q "$q" '{question: $q}')"
	curl -sS -X POST "$BASE_URL/api/qa" \
		-H "Content-Type: application/json" \
		-d "$QA_PAYLOAD" | jq .
done <test_docs/qa_questions.txt

echo "\nSmoke test done. Compare with test_docs/expected_results.md"
