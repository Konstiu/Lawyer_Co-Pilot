# Evaluation Workflow

This document turns the existing test assets into one reproducible evaluation procedure for the Legal Co-Pilot.

## Goal

Evaluate three capabilities:
- extraction quality
- rule-review quality
- Q&A grounding quality

The emphasis is not only whether the answer is useful, but whether it is traceable to the source document.

## Evaluation Assets

Small baseline set:
- `test_docs/baseline/documents/vertrag_1_saas_msa.txt`
- `test_docs/baseline/documents/vertrag_2_it_services.txt`
- `test_docs/baseline/documents/vertrag_3_nda.txt`
- `test_docs/baseline/prompts/extraction_fields.txt`
- `test_docs/baseline/prompts/review_rules.txt`
- `test_docs/baseline/prompts/qa_questions.txt`
- `test_docs/docs/expected_results.md`
- `test_docs/scripts/api_smoketest.sh`
- `test_docs/scripts/benchmark_capture.sh`
- `test_docs/scripts/compare_runs.py`
- `test_docs/templates/eval_result_template.json`

Harder set / larger-document procedure:
- `test_docs/hard/prompts/pdf_hard_extraction_fields.txt`
- `test_docs/hard/prompts/pdf_hard_review_rules.txt`
- `test_docs/hard/prompts/pdf_hard_qa_questions.txt`
- `test_docs/hard/documents/*.docx`
- `test_docs/scripts/pdf_hard_run.sh`
- `test_docs/scripts/run_docx_batch.sh`
- `test_docs/docs/pdf_eval_scorecard.md`

## 1. Baseline Smoke Evaluation

Use this to confirm the system works end-to-end on the checked-in sample documents.

1. Start the app.
2. Run:

```bash
bash test_docs/scripts/api_smoketest.sh
```

If you prefer one Python command that starts the app from `.env`, runs the capture, and writes the comparison report:

```bash
python test_docs/scripts/run_benchmark.py
```

3. Compare the outputs against:

```text
test_docs/docs/expected_results.md
```

Baseline pass criteria:
- extraction values broadly match the expected fields
- review labels are directionally correct (`ok`, `deviation`, `missing`)
- Q&A answers stay concise and cite supporting passages
- missing information is reported as missing instead of invented

To save one run as structured artifacts plus coverage-style summary metrics:

```bash
bash test_docs/scripts/benchmark_capture.sh
```

This writes:
- raw JSON outputs for documents, extraction, review, and Q&A
- `summary.json` with citation/page coverage, status distributions, and model metadata

To compare multiple saved runs, generate a markdown report:

```bash
python test_docs/scripts/compare_runs.py --output test_runs/model_comparison_report.md
```

How to interpret the comparison report:
- `Extract Quote %`: share of extracted fields that include a supporting quote. Higher is better because the extraction is easier to verify.
- `Extract Page %`: share of extracted fields that include a page reference. Higher is better because the supporting passage is easier to locate.
- `Review Quote %`: share of review findings that include a supporting quote. Higher is better because each classification is more directly auditable.
- `Review Page %`: share of review findings that include a page reference. Higher is better because the cited passage is easier to inspect.
- `QA w/ Sources %`: share of question-answer results that include at least one source reference. Higher is better because answers are more clearly grounded in the documents.
- `Avg Sources`: average number of sources attached to each answer. This is not a simple "higher is better" metric. Too few sources can mean weak grounding, while too many can indicate noisy retrieval or unfocused answers.

Important interpretation note:
- these metrics measure traceability and auditability, not legal correctness by themselves
- a run with high quote or page coverage can still contain incorrect extractions, weak legal reasoning, or unsupported conclusions
- always pair the report with manual checks against `test_docs/docs/expected_results.md` and the grading guidance below

Use `test_docs/templates/eval_result_template.json` to record the final judged metrics you want to cite in a poster or report.

## 2. Hard Evaluation

Use this when testing larger or more structurally difficult documents.

If the documents are already indexed:

```bash
bash test_docs/scripts/pdf_hard_run.sh
```

If the starting point is the provided DOCX sample directory:

```bash
bash test_docs/scripts/run_docx_batch.sh
```

Then grade the outputs with:

```text
test_docs/docs/pdf_eval_scorecard.md
```

## 3. What To Measure

Extraction:
- correct `status`
- factually correct `value`
- quote actually supports the value
- page / location hint is plausible

Rule review:
- correct class: `ok`, `deviation`, or `missing`
- explanation is legally consistent with the passage
- citation is specific enough to audit

Q&A:
- directly answers the question
- uses only source-grounded claims
- combines multi-document evidence correctly
- explicitly states when the answer is not derivable from the retrieved passages

## 4. Suggested Reporting Format

For the poster or report, summarize results by capability rather than pasting raw output.

Recommended categories:
- extraction correctness
- review classification correctness
- citation correctness / page plausibility
- grounded Q&A answer quality

Use the traffic-light interpretation from `test_docs/docs/pdf_eval_scorecard.md`:
- green: `>= 85%`
- yellow: `70-84%`
- red: `< 70%`

## 5. Known Failure Modes To Note

When recording results, explicitly note these observed limitations:
- absence detection can be unreliable
- tables and nested clauses may lose structure during chunking
- page references can weaken on long or layout-heavy documents
- rule translation from natural language to machine-checkable checks is brittle

These limitations should be reported together with the results so evaluation remains honest and auditable.
