#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_environment


def wait_for_server(base_url: str, timeout_s: float = 45.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url, timeout=2.0) as resp:
                if 200 <= resp.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError(f"Server did not become ready within {timeout_s}s: {base_url}")


def run_command(cmd: list[str], env: dict[str, str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the app from .env and run the benchmark capture.")
    parser.add_argument("--base-url", default=None, help="Override benchmark base URL")
    parser.add_argument("--skip-compare", action="store_true", help="Skip model-comparison report generation")
    parser.add_argument("--compare-output", default="test_runs/model_comparison_report.md", help="Markdown report path for compare_runs.py")
    parser.add_argument("--server-timeout", type=float, default=45.0, help="Seconds to wait for the local server to become ready")
    parser.add_argument("--keep-server", action="store_true", help="Do not stop the server after the benchmark finishes")
    args = parser.parse_args()

    load_environment()

    env = os.environ.copy()
    host = env.get("APP_HOST", "127.0.0.1")
    port = env.get("APP_PORT", "8000")
    base_url = args.base_url or env.get("BASE_URL") or f"http://{host}:{port}"
    env["BASE_URL"] = base_url
    env.setdefault("CORPUS_LABEL", "user_docs")
    env.setdefault("DATASET_LABEL", "baseline")

    server = subprocess.Popen(
        [sys.executable, "run_server.py"],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )

    try:
        wait_for_server(base_url, timeout_s=args.server_timeout)
        run_command(["bash", "test_docs/scripts/benchmark_capture.sh"], env=env, cwd=ROOT)
        if not args.skip_compare:
            run_command(
                [sys.executable, "test_docs/scripts/compare_runs.py", "--output", args.compare_output],
                env=env,
                cwd=ROOT,
            )
    finally:
        if not args.keep_server and server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
