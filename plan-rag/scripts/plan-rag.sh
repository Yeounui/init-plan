#!/usr/bin/env bash
set -euo pipefail

# Repo that holds the plan_rag package and its uv project (this script lives in
# <repo>/scripts/; the package is a flat plan_rag/ at the repo root).
SCRIPT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${SCRIPT_REPO}/.venv/bin/python"

# The consuming project is the explicit project root or the MCP launch cwd. Its
# plan/ docs and .plan-rag state are rooted here, and its .env carries runtime
# config (PLAN_RAG_EMBEDDING_*, PLAN_RAG_STATE_DIR, ...) that plan_rag reads
# from os.environ only.
CONSUMER_ROOT_VALUE="${PLAN_RAG_PROJECT_ROOT:-${PWD}}"
if [[ ! -d "${CONSUMER_ROOT_VALUE}" ]]; then
  printf 'plan-rag: project root does not exist: %s\n' "${CONSUMER_ROOT_VALUE}" >&2
  exit 1
fi
CONSUMER_ROOT="$(cd "${CONSUMER_ROOT_VALUE}" && pwd)"
if [[ -f "${CONSUMER_ROOT}/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
    if [[ "$line" =~ ^(PLAN_RAG_[A-Z0-9_]+|LLAMA_PID_FILE)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      # Strip one layer of matching surrounding quotes (the near-universal
      # hand-edited .env convention), then backslash-escaping from legacy
      # `%q`-quoted files; current setup-plan-rag.sh writes plain values.
      if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
        value="${BASH_REMATCH[1]}"
      fi
      export "${key}=${value//\\/}"
    fi
  done < "${CONSUMER_ROOT}/.env"
fi

# Plan RAG runs from its own uv-managed .venv inside this repo — no ambient
# interpreter, no shared environment to keep in sync. Build it on first use;
# uv resolves nothing at runtime because uv.lock is committed. Progress goes to
# stderr: stdout carries MCP JSON-RPC only.
if [[ ! -x "${VENV_PYTHON}" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    printf 'plan-rag: uv is required and was not found on PATH.\n' >&2
    printf 'plan-rag: install it (https://docs.astral.sh/uv/) then run: uv sync --frozen --project %s\n' "${SCRIPT_REPO}" >&2
    exit 1
  fi
  printf 'plan-rag: creating %s/.venv from uv.lock (first run, this takes a while)\n' "${SCRIPT_REPO}" >&2
  uv sync --frozen --project "${SCRIPT_REPO}" >&2
fi

# Drop any inherited PYTHONPATH/PYTHONHOME: plan_rag lives in the venv, and an
# ambient path (ROS, conda, another project) would otherwise shadow its
# dependencies.
exec env -u PYTHONPATH -u PYTHONHOME "${VENV_PYTHON}" \
  -m plan_rag.cli --project-root "${CONSUMER_ROOT}" "$@"
