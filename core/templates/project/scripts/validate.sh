#!/usr/bin/env bash
# validate.sh: this repo's canonical validation. Run `bash scripts/validate.sh` before every commit.
# It runs the checks the repo has and skips the rest, so a new repo passes until you add your own.
# Add your tests, linters and type checks where marked below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# managed:validate-queue block, kept in step by sync-hooks and bootstrap
# One per-user queue for validation runs, taken through the validate-queue helper this machine installs.
# Without the helper the run goes ahead unqueued.
VALIDATE_QUEUE_BIN="${VALIDATE_QUEUE_BIN:-$HOME/.local/bin/validate-queue}"
if [[ -z "${VALIDATE_QUEUE_SLOT:-}" ]]; then
  if [[ -x "$VALIDATE_QUEUE_BIN" ]]; then
    VALIDATE_QUEUE_SLOT="$("$VALIDATE_QUEUE_BIN" acquire --pid $$ --label "$(basename "${REPO_ROOT:-$PWD}")" || true)"
    export VALIDATE_QUEUE_SLOT="${VALIDATE_QUEUE_SLOT:-none}"
    # A script's own EXIT trap wins: the queue reaps a slot whose process has exited, so nothing leaks.
    [[ -n "$(trap -p EXIT)" ]] || trap '"$VALIDATE_QUEUE_BIN" release "$VALIDATE_QUEUE_SLOT" >/dev/null 2>&1 || true' EXIT
  else
    echo "validate: no validate-queue helper at $VALIDATE_QUEUE_BIN, running unqueued" >&2
  fi
fi

# bash runs the hook whether or not its executable bit survived a copy, so the gates never skip silently.
if [[ -f .githooks/pre-commit ]]; then
  echo "=== validate: pre-commit gates ==="
  OLIVERCODE_SCAN_TREE=1 bash .githooks/pre-commit
fi

if [[ -f scripts/check-structure-contract.mjs ]] && command -v node >/dev/null 2>&1; then
  echo "=== validate: structure contract ==="
  node scripts/check-structure-contract.mjs
fi

if [[ -f package.json ]] && command -v npm >/dev/null 2>&1 \
   && python3 -c "import json,sys; sys.exit(0 if 'validate' in json.load(open('package.json')).get('scripts',{}) else 1)"; then
  echo "=== validate: npm run validate ==="
  npm run -s validate
fi

# Add this repo's own checks here, for example: pytest, ruff, tsc.

echo "=== validate: passed ==="
