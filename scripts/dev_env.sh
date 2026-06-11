#!/usr/bin/env bash
# Source this file to activate venv + runtime config:
#   source scripts/dev_env.sh

set -a

# --- Python env ---
source venv/bin/activate

if [[ -f .env ]]; then
  source .env
fi

set +a

echo "Environment loaded. LLM_PROVIDER=${LLM_PROVIDER:-unset}, DATA_DIR=${DATA_DIR:-unset}"
