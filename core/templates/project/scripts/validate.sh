#!/usr/bin/env bash
# validate.sh: this repo's canonical validation. Run `bash scripts/validate.sh` before every commit.
# It runs the checks the repo has and skips the rest, so a new repo passes until you add your own.
# Add your tests, linters and type checks where marked below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# bash runs the hook whether or not its executable bit survived a copy, so the gates never skip silently.
if [[ -f .githooks/pre-commit ]]; then
  echo "=== validate: pre-commit gates ==="
  OLIVERCODE_SCAN_TREE=1 bash .githooks/pre-commit
fi

if [[ -f scripts/check-structure-contract.mjs ]] && command -v node >/dev/null 2>&1; then
  echo "=== validate: structure contract ==="
  node scripts/check-structure-contract.mjs
fi

# The repo's own tests. This mirrors the detector in OliverCode's scripts/lib/repo_profiles.py (validation_commands): the first npm script named validate, check or test,
# else pytest, go test, cargo test or make test, whichever the repo has.
run_check() { echo "=== validate: $* ==="; "$@"; }
# The npm init placeholder test script ("no test specified") is not a test, so it never counts.
npm_script() { python3 -c "import json,sys; s=json.load(open('package.json')).get('scripts',{}); sys.exit(0 if '$1' in s and not ('$1' == 'test' and 'no test specified' in str(s['$1'])) else 1)" 2>/dev/null; }
if [[ -f package.json ]] && command -v npm >/dev/null 2>&1 && npm_script validate; then
  run_check npm run -s validate
elif [[ -f package.json ]] && command -v npm >/dev/null 2>&1 && npm_script check; then
  run_check npm run -s check
elif [[ -f package.json ]] && command -v npm >/dev/null 2>&1 && npm_script test; then
  run_check npm test --silent
elif command -v pytest >/dev/null 2>&1 && { [[ -f pytest.ini || -f conftest.py || -f tox.ini ]] || grep -qs pytest pyproject.toml setup.cfg requirements.txt requirements-dev.txt; }; then
  run_check pytest -q
elif [[ -f go.mod ]] && command -v go >/dev/null 2>&1; then
  run_check go test ./...
elif [[ -f Cargo.toml ]] && command -v cargo >/dev/null 2>&1; then
  run_check cargo test
elif grep -qs '^test:' Makefile && command -v make >/dev/null 2>&1; then
  run_check make test
fi

# Add this repo's own extra checks here, for example: ruff, tsc.

echo "=== validate: passed ==="
