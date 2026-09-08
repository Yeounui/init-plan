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
  set -a
  # shellcheck disable=SC1091
  source "${CONSUMER_ROOT}/.env"
  set +a
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

exec "${VENV_PYTHON}" -m plan_rag.cli --project-root "${CONSUMER_ROOT}" "$@"
