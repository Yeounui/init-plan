#!/usr/bin/env bash
# .claude/check.sh — the project's single build+test gate.
#
# /run-phase's build-fixer runs it exactly once per phase and the Stop hook in
# .claude/settings.json runs it when source files are dirty. Fill the three
# command arrays from plan/ARCHITECTURE.md > Toolchain. Keep the exit code
# honest: never pipe a step into `tail`, and keep the final OK line last —
# callers grep for it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# From Toolchain. Leave an array empty to skip that step.
CONFIGURE_CMD=(REPLACE_FROM_TOOLCHAIN)   # e.g. (cmake --preset default)  or  (uv sync --frozen)
BUILD_CMD=(REPLACE_FROM_TOOLCHAIN)       # e.g. (cmake --build build -j"$(nproc)")  or  ()
TEST_CMD=(REPLACE_FROM_TOOLCHAIN)        # e.g. (ctest --test-dir build --output-on-failure)  or  (uv run pytest -q)
CONFIGURED_MARKER=""                     # e.g. build/CMakeCache.txt — configure runs only while this is absent

if [ "${#CONFIGURE_CMD[@]}" -gt 0 ] && [ -z "$CONFIGURED_MARKER" -o ! -e "$CONFIGURED_MARKER" ]; then
  echo "=== Configuring ==="
  "${CONFIGURE_CMD[@]}"
fi

if [ "${#BUILD_CMD[@]}" -gt 0 ]; then
  echo "=== Building ==="
  if ! "${BUILD_CMD[@]}"; then
    echo "FAIL: build"
    exit 1
  fi
fi

echo "=== Testing ==="
if ! "${TEST_CMD[@]}"; then
  echo ""
  echo "FAIL: tests"
  exit 1
fi

echo ""
echo "OK: build + tests passed"
