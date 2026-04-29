#!/usr/bin/env bash
# Source this file to activate venv + runtime config:
#   source scripts/dev_env.sh

set -a

# --- Python env ---
source venv/bin/activate

# --- Provider / models ---
export LLM_PROVIDER="gemini"
export GEMINI_MODEL="gemini-2.5-flash-lite"
export GEMINI_EMBED_MODEL="text-embedding-004"

# --- Vertex AI auth/billing ---
export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="appliedgenai-494416"
export GOOGLE_CLOUD_LOCATION="europe-west4"

# --- App/runtime ---
export DATA_DIR="./data"
export CHUNK_SIZE="1500"
export CHUNK_OVERLAP="200"
export MIN_CHUNK_CHARS="80"
export RETRIEVE_CANDIDATE_MULTIPLIER="3"
export RETRIEVE_EXPAND_NEIGHBORS="1"

# --- Throughput/retries ---
export EMBED_BATCH_SIZE="64"
export EMBED_MAX_RETRIES="3"
export EMBED_RETRY_BASE_SECONDS="1.0"
export EXTRACT_MAX_CONCURRENCY="6"
export REVIEW_MAX_CONCURRENCY="6"
export QA_TOP_K="6"

set +a

echo "Environment loaded. LLM_PROVIDER=${LLM_PROVIDER}, PROJECT=${GOOGLE_CLOUD_PROJECT}, DATA_DIR=${DATA_DIR}"
