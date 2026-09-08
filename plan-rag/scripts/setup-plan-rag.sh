#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup-plan-rag.sh --model-path PATH [--project-root PATH]

Installs the locked Plan RAG runtime, records the local BGE-M3 model path in
the consumer project's .env, adds .plan-rag/ to its .gitignore, copies missing
Plan RAG rules, and verifies the installation. It never downloads a model or
overwrites existing rule files.
EOF
}

MODEL_PATH=''
PROJECT_ROOT="$PWD"
while (($#)); do
  case "$1" in
    --model-path) MODEL_PATH=${2:?--model-path requires a path}; shift 2 ;;
    --project-root) PROJECT_ROOT=${2:?--project-root requires a path}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n "$MODEL_PATH" ]] || { usage >&2; exit 2; }
[[ -d "$PROJECT_ROOT" ]] || { printf 'plan-rag setup: project root does not exist: %s\n' "$PROJECT_ROOT" >&2; exit 2; }
[[ -d "$MODEL_PATH" ]] || { printf 'plan-rag setup: BGE-M3 model directory does not exist: %s\n' "$MODEL_PATH" >&2; exit 2; }
command -v uv >/dev/null 2>&1 || { printf 'plan-rag setup: install uv first; see README.md.\n' >&2; exit 1; }

SCRIPT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_REPO/.." && pwd)"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
MODEL_PATH="$(cd "$MODEL_PATH" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

set_setting() {
  local key=$1 value=$2 temporary
  temporary="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
  [[ -f "$ENV_FILE" ]] && awk -v key="$key" 'index($0, key "=") != 1' "$ENV_FILE" > "$temporary"
  printf '%s=%s\n' "$key" "$value" >> "$temporary"
  mv "$temporary" "$ENV_FILE"
}

append_if_missing() {
  local key=$1 value=$2
  grep -q "^${key}=" "$ENV_FILE" 2>/dev/null || printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
}

printf 'plan-rag setup: installing locked runtime dependencies\n'
uv sync --frozen --inexact --no-dev --no-install-package torch --project "$SCRIPT_REPO"
UV_TORCH_BACKEND=auto uv pip install --directory "$SCRIPT_REPO" --python "$SCRIPT_REPO/.venv/bin/python" torch

umask 077
touch "$ENV_FILE"
append_if_missing PLAN_RAG_EMBEDDING_BACKEND flag_embedding
set_setting PLAN_RAG_EMBEDDING_MODEL_PATH "$MODEL_PATH"
append_if_missing PLAN_RAG_EMBEDDING_USE_FP16 true
append_if_missing PLAN_RAG_EMBEDDING_DEVICE auto
append_if_missing PLAN_RAG_DOCUMENT_ROOT plan
append_if_missing PLAN_RAG_STATE_DIR .plan-rag
append_if_missing PLAN_RAG_DEBOUNCE_SECONDS 2

touch "$PROJECT_ROOT/.gitignore"
grep -qxF '.plan-rag/' "$PROJECT_ROOT/.gitignore" || printf '\n.plan-rag/\n' >> "$PROJECT_ROOT/.gitignore"
mkdir -p "$PROJECT_ROOT/.claude/rules"
for rule in "$PLUGIN_ROOT"/rules/*.md; do
  destination="$PROJECT_ROOT/.claude/rules/$(basename "$rule")"
  [[ -e "$destination" ]] || cp "$rule" "$destination"
done

printf 'plan-rag setup: verifying configuration\n'
PLAN_RAG_PROJECT_ROOT="$PROJECT_ROOT" "$SCRIPT_REPO/scripts/plan-rag.sh" status
