#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

command -v "$PYTHON_BIN" >/dev/null || {
  echo "Python interpreter not found: $PYTHON_BIN"
  exit 1
}

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PY_VERSION" in
  3.11|3.12) ;;
  *)
    cat <<EOF
Unsupported Python version for the recommended setup: $PY_VERSION

This project should be run with Python 3.11 or 3.12.
Reason: PyMuPDF may otherwise fall back to a local native build instead of using a wheel.

Recommended approach:
- install or manage Python 3.12 with a version manager such as uv
- then rerun this script with:
  PYTHON_BIN=python3.12 bash scripts/setup_local.sh
EOF
    exit 1
    ;;
esac

cd "$ROOT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[1/4] Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "[1/4] Reusing existing virtual environment at $VENV_DIR"
fi

echo "[2/4] Activating virtual environment"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "[3/4] Installing Python dependencies"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  echo "[4/4] Creating .env from .env.example"
  cp .env.example .env
else
  echo "[4/4] Keeping existing .env"
fi

cat <<'EOF'

Setup complete.

Next steps:
1. Edit `.env` with your provider credentials and model settings.
2. Activate the environment in each new shell:
   source venv/bin/activate
3. Start the app:
   python run_server.py
4. Run the benchmark flow:
   python test_docs/scripts/run_benchmark.py
EOF
