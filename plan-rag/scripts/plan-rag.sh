#!/usr/bin/env bash
set -euo pipefail

# Repo that holds the plan_rag package and its pixi workspace (this script lives
# in <repo>/scripts/; the package is a flat plan_rag/ at the repo root).
SCRIPT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# An installed environment wins, so the choice made on first install sticks even
# when an MCP host launches this with a PATH that lacks nvidia-smi.
if [[ -x "${SCRIPT_REPO}/.pixi/envs/default/bin/python" ]]; then
  PIXI_ENVIRONMENT=default
elif [[ -x "${SCRIPT_REPO}/.pixi/envs/cpu/bin/python" ]]; then
  PIXI_ENVIRONMENT=cpu
elif command -v nvidia-smi >/dev/null 2>&1; then
  PIXI_ENVIRONMENT=default
else
  PIXI_ENVIRONMENT=cpu
fi
ENV_PYTHON="${SCRIPT_REPO}/.pixi/envs/${PIXI_ENVIRONMENT}/bin/python"

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

# Plan RAG runs from its own pixi environment inside this repo — no ambient
# interpreter. Build it on first use from the committed pixi.lock; torch is a
# conda-forge package, hardlinked from pixi's shared cache so it is stored once
# for every project pinning the same build. Progress goes to stderr: stdout
# carries MCP JSON-RPC only.
if [[ ! -x "${ENV_PYTHON}" ]]; then
  if ! command -v pixi >/dev/null 2>&1; then
    printf 'plan-rag: pixi is required and was not found on PATH.\n' >&2
    printf 'plan-rag: install it (https://pixi.sh) then run: pixi install --frozen --manifest-path %s -e %s\n' "${SCRIPT_REPO}" "${PIXI_ENVIRONMENT}" >&2
    exit 1
  fi
  printf 'plan-rag: creating the %s environment from pixi.lock (first run, this takes a while)\n' "${PIXI_ENVIRONMENT}" >&2
  pixi install --frozen --manifest-path "${SCRIPT_REPO}" -e "${PIXI_ENVIRONMENT}" >&2
fi

# Drop any inherited PYTHONPATH/PYTHONHOME: plan_rag lives in the environment,
# and an ambient path (ROS, conda, another project) would otherwise shadow its
# dependencies.
exec env -u PYTHONPATH -u PYTHONHOME "${ENV_PYTHON}" \
  -m plan_rag.cli --project-root "${CONSUMER_ROOT}" "$@"
