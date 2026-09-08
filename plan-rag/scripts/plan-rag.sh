#!/usr/bin/env bash
set -euo pipefail

# Repo that holds the plan_rag package (this script lives in <repo>/scripts/, the
# package is a flat plan_rag/ at the repo root — not a src/ layout).
SCRIPT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH_VALUE="${SCRIPT_REPO}"
if [[ -n "${PYTHONPATH:-}" ]]; then
  PYTHONPATH_VALUE="${PYTHONPATH_VALUE}:${PYTHONPATH}"
fi

# Plan RAG always runs in its own pinned conda env, independent of the consuming
# project's CONDA_ENV (which is project-specific). The value is stored here and
# referenced at launch; override with PLAN_RAG_CONDA_ENV only if ever needed.
PLAN_RAG_CONDA_ENV="${PLAN_RAG_CONDA_ENV:-codex}"

# The consuming project is the explicit project root or the MCP launch cwd. Its
# plan/ docs and .plan-rag state are rooted here, and its .env carries runtime config
# (PLAN_RAG_EMBEDDING_*, PLAN_RAG_STATE_DIR, CONDA_SH, ...) that plan_rag reads
# from os.environ only. Source it for that config, but DO NOT use its CONDA_ENV
# for activation — plan-rag pins its own env above.
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

if [[ -z "${CONDA_SH:-}" ]]; then
  printf 'plan-rag: CONDA_SH not set (expected in %s/.env, alongside PLAN_RAG_EMBEDDING_BACKEND and PLAN_RAG_EMBEDDING_MODEL_PATH)\n' "${CONSUMER_ROOT}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${CONDA_SH}"
conda activate "${PLAN_RAG_CONDA_ENV}"
exec env PYTHONPATH="${PYTHONPATH_VALUE}" \
  python -m plan_rag.cli --project-root "${CONSUMER_ROOT}" "$@"
