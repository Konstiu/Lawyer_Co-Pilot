#!/usr/bin/env python3
"""
Ingest legal knowledge documents (e.g., RIS exports/manual downloads) into corpus=legal_knowledge.

Usage examples:
  python scripts/ingest_legal_corpus.py --url-list data/legal_seed_urls.txt --jurisdiction AT
  python scripts/ingest_legal_corpus.py --input-dir ./seed_laws --jurisdiction AT
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_environment
from app.ingestion import ingest_document

load_environment()


def _safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "document.txt"
    if "." not in name:
        name += ".txt"
    return name


def _html_to_text(content: bytes) -> bytes:
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.encode("utf-8")


def _fetch_url(url: str, timeout_s: float = 45.0) -> tuple[str, bytes]:
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        filename = _safe_filename_from_url(url)
        content = resp.content
        if "text/html" in ctype or filename.lower().endswith((".htm", ".html")):
            filename = Path(filename).with_suffix(".txt").name
            content = _html_to_text(content)
        return filename, content


def _iter_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-list", type=Path, help="Path to newline-separated URLs")
    parser.add_argument("--input-dir", type=Path, help="Directory with pdf/txt/docx files")
    parser.add_argument("--jurisdiction", default="AT", help="e.g. AT")
    parser.add_argument("--source-type", default="statute", help="e.g. statute/case_law/commentary")
    parser.add_argument("--sleep-seconds", type=float, default=1.5, help="Delay between URL fetches")
    args = parser.parse_args()

    if not args.url_list and not args.input_dir:
        raise SystemExit("Provide --url-list and/or --input-dir")

    total = 0
    ingested = 0

    if args.input_dir:
        for path in sorted(args.input_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".pdf", ".txt", ".md", ".docx"}:
                continue
            total += 1
            result = ingest_document(
                filename=path.name,
                content=path.read_bytes(),
                corpus="legal_knowledge",
                metadata={
                    "source_type": args.source_type,
                    "source_url": str(path.resolve()),
                    "jurisdiction": args.jurisdiction,
                },
            )
            if result.get("status") in {"ingested", "already_exists"}:
                ingested += 1
            print(f"[file] {path.name}: {result.get('status')}")

    if args.url_list:
        for url in _iter_urls(args.url_list):
            total += 1
            try:
                filename, content = _fetch_url(url)
                result = ingest_document(
                    filename=filename,
                    content=content,
                    corpus="legal_knowledge",
                    metadata={
                        "source_type": args.source_type,
                        "source_url": url,
                        "jurisdiction": args.jurisdiction,
                    },
                )
                if result.get("status") in {"ingested", "already_exists"}:
                    ingested += 1
                print(f"[url] {url}: {result.get('status')}")
            except Exception as exc:
                print(f"[url] {url}: error ({type(exc).__name__}) {exc}")
            time.sleep(max(0.0, args.sleep_seconds))

    print(f"Done. processed={total} accepted={ingested}")


if __name__ == "__main__":
    main()
