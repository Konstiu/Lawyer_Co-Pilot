#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def fmt_num(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def row_for(summary: dict, run_dir: Path) -> list[str]:
    extraction = summary.get("extraction", {})
    review = summary.get("review", {})
    qa = summary.get("qa", {})
    return [
        summary.get("run_id", run_dir.name),
        summary.get("model_provider", "-"),
        summary.get("model_name", "-"),
        summary.get("dataset", "-"),
        summary.get("corpus", "-"),
        fmt_num(extraction.get("quote_coverage_pct")),
        fmt_num(extraction.get("page_coverage_pct")),
        fmt_num(review.get("quote_coverage_pct")),
        fmt_num(review.get("page_coverage_pct")),
        fmt_num(qa.get("answers_with_sources_pct")),
        fmt_num(qa.get("avg_sources_per_answer")),
    ]


def to_markdown(rows: list[list[str]]) -> str:
    headers = [
        "Run ID",
        "Provider",
        "Model",
        "Dataset",
        "Corpus",
        "Extract Quote %",
        "Extract Page %",
        "Review Quote %",
        "Review Page %",
        "QA w/ Sources %",
        "Avg Sources",
    ]
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        table.append("| " + " | ".join(row) + " |")
    return "\n".join(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a markdown comparison report from benchmark runs.")
    parser.add_argument("--runs-dir", default="test_runs", help="Directory containing benchmark run folders")
    parser.add_argument("--output", help="Optional markdown output path")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    rows: list[list[str]] = []
    for run_dir in sorted(runs_dir.iterdir()) if runs_dir.exists() else []:
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = load_summary(summary_path)
        if not summary:
            continue
        rows.append(row_for(summary, run_dir))

    report_lines = ["# Model Comparison Report", ""]
    if not rows:
        report_lines.append("No benchmark summaries found.")
    else:
        report_lines.append(
            "This report compares saved benchmark runs using the structural coverage metrics captured during evaluation."
        )
        report_lines.append("")
        report_lines.append(to_markdown(rows))

    report = "\n".join(report_lines) + "\n"
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
