#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
OUT_ROOT="${OUT_ROOT:-test_runs}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_ROOT}/${RUN_ID}"
DATASET_LABEL="${DATASET_LABEL:-baseline}"
CORPUS_LABEL="${CORPUS_LABEL:-user_docs}"

LLM_PROVIDER="${LLM_PROVIDER:-openai}"
if [[ "$LLM_PROVIDER" == "gemini" ]]; then
  MODEL_NAME="${GEMINI_MODEL:-unknown}"
  EMBED_MODEL_NAME="${GEMINI_EMBED_MODEL:-unknown}"
elif [[ "$LLM_PROVIDER" == "ollama" ]]; then
  MODEL_NAME="${OLLAMA_CHAT_MODEL:-unknown}"
  EMBED_MODEL_NAME="${OLLAMA_EMBED_MODEL:-unknown}"
elif [[ "$LLM_PROVIDER" == "openai" ]]; then
  MODEL_NAME="${OPENAI_MODEL:-gpt-4o}"
  EMBED_MODEL_NAME="${EMBED_MODEL:-text-embedding-3-small}"
else
  MODEL_NAME="${MODEL_NAME:-local_fallback}"
  EMBED_MODEL_NAME="${EMBED_MODEL:-local_fallback}"
fi

command -v curl >/dev/null || { echo "curl fehlt"; exit 1; }
command -v jq >/dev/null || { echo "jq fehlt"; exit 1; }

mkdir -p "$OUT_DIR"

echo "Using BASE_URL=$BASE_URL"
echo "Saving run artifacts to $OUT_DIR"
echo "Model provider=$LLM_PROVIDER model=$MODEL_NAME embed=$EMBED_MODEL_NAME"

cat > "$OUT_DIR/metadata.json" <<EOF
{
  "run_id": "$RUN_ID",
  "generated_at": "$(date -Iseconds)",
  "base_url": "$BASE_URL",
  "dataset": "$DATASET_LABEL",
  "corpus": "$CORPUS_LABEL",
  "model_provider": "$LLM_PROVIDER",
  "model_name": "$MODEL_NAME",
  "embedding_model": "$EMBED_MODEL_NAME",
  "jurisdiction_scope": "AT-focused / configurable corpus"
}
EOF

echo "[1/6] Upload baseline documents"
for f in test_docs/baseline/documents/vertrag_1_saas_msa.txt test_docs/baseline/documents/vertrag_2_it_services.txt test_docs/baseline/documents/vertrag_3_nda.txt; do
  echo "  -> $f"
  curl -sS -X POST "$BASE_URL/api/documents/upload" -F "file=@$f" | jq . > /dev/null
done

echo "[2/6] Capture document inventory"
curl -sS "$BASE_URL/api/documents" | jq . > "$OUT_DIR/documents.json"

echo "[3/6] Run extraction"
EXTRACT_PAYLOAD="$(jq -Rn --rawfile f test_docs/baseline/prompts/extraction_fields.txt '{fields: ($f | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/extract" \
  -H "Content-Type: application/json" \
  -d "$EXTRACT_PAYLOAD" | jq . > "$OUT_DIR/extraction.json"

echo "[4/6] Run rule review"
REVIEW_PAYLOAD="$(jq -Rn --rawfile r test_docs/baseline/prompts/review_rules.txt '{rules: ($r | split("\n") | map(select(length>0)))}')"
curl -sS -X POST "$BASE_URL/api/review" \
  -H "Content-Type: application/json" \
  -d "$REVIEW_PAYLOAD" | jq . > "$OUT_DIR/review.json"

echo "[5/6] Run Q&A batch"
QA_RESULTS='[]'
while IFS= read -r q; do
  [[ -z "$q" ]] && continue
  QA_PAYLOAD="$(jq -Rn --arg q "$q" '{question: $q}')"
  ANSWER="$(curl -sS -X POST "$BASE_URL/api/qa" \
    -H "Content-Type: application/json" \
    -d "$QA_PAYLOAD" | jq --arg question "$q" '. + {question: $question}')"
  QA_RESULTS="$(jq --argjson item "$ANSWER" '. + [$item]' <<<"$QA_RESULTS")"
done < test_docs/baseline/prompts/qa_questions.txt
printf '%s\n' "$QA_RESULTS" | jq . > "$OUT_DIR/qa.json"

echo "[6/6] Build summary"
jq -n \
  --arg run_id "$RUN_ID" \
  --arg generated_at "$(date -Iseconds)" \
  --arg base_url "$BASE_URL" \
  --arg dataset "$DATASET_LABEL" \
  --arg corpus "$CORPUS_LABEL" \
  --arg model_provider "$LLM_PROVIDER" \
  --arg model_name "$MODEL_NAME" \
  --arg embedding_model "$EMBED_MODEL_NAME" \
  --slurpfile docs "$OUT_DIR/documents.json" \
  --slurpfile extraction "$OUT_DIR/extraction.json" \
  --slurpfile review "$OUT_DIR/review.json" \
  --slurpfile qa "$OUT_DIR/qa.json" '
  def count_status(items; key):
    reduce items[] as $item ({}; .[$item[key]] = ((.[$item[key]] // 0) + 1));

  def pct(part; total):
    if total == 0 then 0 else ((part / total) * 10000 | round) / 100 end;

  ($docs[0] // []) as $doc_list |
  ($extraction[0].rows // []) as $rows |
  ($review[0].findings // []) as $findings |
  ($qa[0] // []) as $answers |
  [ $rows[]?.cells | to_entries[] | .value ] as $cells |
  {
    run_id: $run_id,
    generated_at: $generated_at,
    base_url: $base_url,
    dataset: $dataset,
    corpus: $corpus,
    model_provider: $model_provider,
    model_name: $model_name,
    embedding_model: $embedding_model,
    documents: {
      count: ($doc_list | length)
    },
    extraction: {
      total_cells: ($cells | length),
      status_counts: count_status($cells; "status"),
      quote_coverage_pct: pct(([ $cells[] | select((.quote // "") != "") ] | length); ($cells | length)),
      page_coverage_pct: pct(([ $cells[] | select(.page != null) ] | length); ($cells | length))
    },
    review: {
      total_findings: ($findings | length),
      status_counts: count_status($findings; "status"),
      quote_coverage_pct: pct(([ $findings[] | select((.quote // "") != "") ] | length); ($findings | length)),
      page_coverage_pct: pct(([ $findings[] | select(.page != null) ] | length); ($findings | length))
    },
    qa: {
      total_questions: ($answers | length),
      answers_with_sources_pct: pct(([ $answers[] | select((.sources // []) | length > 0) ] | length); ($answers | length)),
      avg_sources_per_answer: (
        if ($answers | length) == 0 then 0
        else (([ $answers[] | (.sources // [] | length) ] | add) / ($answers | length) * 100 | round) / 100
        end
      )
    }
  }' > "$OUT_DIR/summary.json"

cat > "$OUT_DIR/README.txt" <<EOF
Benchmark capture complete.

Artifacts:
- metadata.json
- documents.json
- extraction.json
- review.json
- qa.json
- summary.json

Interpretation:
- summary.json gives structural coverage metrics for auditability
- metadata.json records which model/config produced the run
- use test_docs/docs/expected_results.md for baseline correctness checks
- use test_docs/docs/pdf_eval_scorecard.md for manual grading on harder document sets
EOF

echo "Done. Summary written to $OUT_DIR/summary.json"
