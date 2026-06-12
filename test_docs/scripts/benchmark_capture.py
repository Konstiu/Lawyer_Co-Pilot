#!/usr/bin/env python3
"""Windows-compatible replacement for benchmark_capture.sh"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BASE_URL    = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
OUT_ROOT    = os.environ.get("OUT_ROOT", "test_runs")
RUN_ID      = os.environ.get("RUN_ID", datetime.now().strftime("%Y%m%d_%H%M%S"))
OUT_DIR     = Path(OUT_ROOT) / RUN_ID
DATASET     = os.environ.get("DATASET_LABEL", "baseline")
CORPUS      = os.environ.get("CORPUS_LABEL", "user_docs")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
if LLM_PROVIDER == "gemini":
    MODEL_NAME       = os.environ.get("GEMINI_MODEL", "unknown")
    EMBED_MODEL_NAME = os.environ.get("GEMINI_EMBED_MODEL", "unknown")
elif LLM_PROVIDER == "ollama":
    MODEL_NAME       = os.environ.get("OLLAMA_CHAT_MODEL", "unknown")
    EMBED_MODEL_NAME = os.environ.get("OLLAMA_EMBED_MODEL", "unknown")
elif LLM_PROVIDER == "openai":
    MODEL_NAME       = os.environ.get("OPENAI_MODEL", "gpt-4o")
    EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
else:
    MODEL_NAME       = os.environ.get("MODEL_NAME", "local_fallback")
    EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "local_fallback")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_dependencies() -> None:
    """Check that required tools are available (curl + jq replaced by requests + json)."""
    try:
        import requests  # noqa: F401
    except ImportError:
        print("'requests' library missing. Run: pip install requests")
        sys.exit(1)


def api_get(path: str) -> dict:
    import requests
    resp = requests.get(f"{BASE_URL}{path}", timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_post_json(path: str, payload: dict) -> dict:
    import requests
    resp = requests.post(f"{BASE_URL}{path}", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def api_post_file(path: str, filepath: Path) -> dict:
    import requests
    with open(filepath, "rb") as f:
        resp = requests.post(f"{BASE_URL}{path}", files={"file": f}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_lines(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def count_status(items: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key)
        if val is not None:
            counts[val] = counts.get(val, 0) + 1
    return counts


def pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round((part / total) * 10000) / 100


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    check_dependencies()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Using BASE_URL={BASE_URL}")
    print(f"Saving run artifacts to {OUT_DIR}")
    print(f"Model provider={LLM_PROVIDER} model={MODEL_NAME} embed={EMBED_MODEL_NAME}")

    # Metadata
    metadata = {
        "run_id": RUN_ID,
        "generated_at": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "dataset": DATASET,
        "corpus": CORPUS,
        "model_provider": LLM_PROVIDER,
        "model_name": MODEL_NAME,
        "embedding_model": EMBED_MODEL_NAME,
        "jurisdiction_scope": "AT-focused / configurable corpus",
    }
    write_json(OUT_DIR / "metadata.json", metadata)

    # [1/6] Upload baseline documents
    print("[1/6] Upload baseline documents")
    docs_to_upload = [
        ROOT / "test_docs/baseline/documents/vertrag_1_saas_msa.txt",
        ROOT / "test_docs/baseline/documents/vertrag_2_it_services.txt",
        ROOT / "test_docs/baseline/documents/vertrag_3_nda.txt",
    ]
    for f in docs_to_upload:
        print(f"  -> {f}")
        api_post_file("/api/documents/upload", f)

    # [2/6] Document inventory
    print("[2/6] Capture document inventory")
    documents = api_get("/api/documents")
    write_json(OUT_DIR / "documents.json", documents)

    # [3/6] Extraction
    print("[3/6] Run extraction")
    fields = read_lines(ROOT / "test_docs/baseline/prompts/extraction_fields.txt")
    extraction = api_post_json("/api/extract", {"fields": fields})
    write_json(OUT_DIR / "extraction.json", extraction)

    # [4/6] Rule review
    print("[4/6] Run rule review")
    rules = read_lines(ROOT / "test_docs/baseline/prompts/review_rules.txt")
    review = api_post_json("/api/review", {"rules": rules})
    write_json(OUT_DIR / "review.json", review)

    # [5/6] Q&A batch
    print("[5/6] Run Q&A batch")
    questions = read_lines(ROOT / "test_docs/baseline/prompts/qa_questions.txt")
    qa_results = []
    for q in questions:
        answer = api_post_json("/api/qa", {"question": q})
        answer["question"] = q
        qa_results.append(answer)
    write_json(OUT_DIR / "qa.json", qa_results)

    # [6/6] Build summary
    print("[6/6] Build summary")
    doc_list  = documents if isinstance(documents, list) else []
    rows      = extraction.get("rows", []) if isinstance(extraction, dict) else []
    findings  = review.get("findings", []) if isinstance(review, dict) else []
    answers   = qa_results

    cells = [
        cell
        for row in rows
        for cell in (row.get("cells") or {}).values()
    ]

    total_cells = len(cells)
    total_findings = len(findings)
    total_answers = len(answers)

    summary = {
        "run_id": RUN_ID,
        "generated_at": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "dataset": DATASET,
        "corpus": CORPUS,
        "model_provider": LLM_PROVIDER,
        "model_name": MODEL_NAME,
        "embedding_model": EMBED_MODEL_NAME,
        "documents": {
            "count": len(doc_list),
        },
        "extraction": {
            "total_cells": total_cells,
            "status_counts": count_status(cells, "status"),
            "quote_coverage_pct": pct(sum(1 for c in cells if c.get("quote", "")), total_cells),
            "page_coverage_pct":  pct(sum(1 for c in cells if c.get("page") is not None), total_cells),
        },
        "review": {
            "total_findings": total_findings,
            "status_counts": count_status(findings, "status"),
            "quote_coverage_pct": pct(sum(1 for f in findings if f.get("quote", "")), total_findings),
            "page_coverage_pct":  pct(sum(1 for f in findings if f.get("page") is not None), total_findings),
        },
        "qa": {
            "total_questions": total_answers,
            "answers_with_sources_pct": pct(
                sum(1 for a in answers if len(a.get("sources") or []) > 0),
                total_answers,
            ),
            "avg_sources_per_answer": (
                round(sum(len(a.get("sources") or []) for a in answers) / total_answers * 100) / 100
                if total_answers > 0 else 0
            ),
        },
    }
    write_json(OUT_DIR / "summary.json", summary)

    readme = (
        "Benchmark capture complete.\n\n"
        "Artifacts:\n"
        "- metadata.json\n"
        "- documents.json\n"
        "- extraction.json\n"
        "- review.json\n"
        "- qa.json\n"
        "- summary.json\n\n"
        "Interpretation:\n"
        "- summary.json gives structural coverage metrics for auditability\n"
        "- metadata.json records which model/config produced the run\n"
        "- use test_docs/docs/expected_results.md for baseline correctness checks\n"
        "- use test_docs/docs/pdf_eval_scorecard.md for manual grading on harder document sets\n"
    )
    (OUT_DIR / "README.txt").write_text(readme, encoding="utf-8")

    print(f"Done. Summary written to {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()