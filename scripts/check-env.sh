#!/usr/bin/env bash
# Warn when the consuming project's .env lacks what Plan RAG needs. Read-only —
# this never writes .env; it tells the user (and Claude) exactly what to add.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
ENV_FILE="${ROOT}/.env"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-the init-plan plugin directory}"

missing=()
for key in CONDA_SH PLAN_RAG_EMBEDDING_MODEL_PATH; do
  if [[ ! -f "${ENV_FILE}" ]] || ! grep -qE "^[[:space:]]*${key}=[^[:space:]]" "${ENV_FILE}"; then
    missing+=("${key}")
  fi
done

(( ${#missing[@]} == 0 )) && exit 0

cat <<MSG
init-plan: the plan-rag MCP server is not configured for this project and will
fail to start. Missing from ${ENV_FILE}: ${missing[*]}

Add these lines to ${ENV_FILE} (full template: ${PLUGIN_ROOT}/.env.example):

  CONDA_SH=/path/to/conda.sh
  PLAN_RAG_EMBEDDING_BACKEND=flag_embedding
  PLAN_RAG_EMBEDDING_MODEL_PATH=/path/to/local/bge-m3

Ask the user for the two paths rather than guessing them, then restart Claude
Code so the MCP server picks up the new values.
MSG
