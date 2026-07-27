#!/usr/bin/env bash
# ─── Run Full QA Pass on a Target Repo ───────────────────────────────────
# Thin wrapper: runs full-qa-pass.sh (the canonical phase list) against the
# repo this script is invoked from, and tees the output to .qa-results/.
# It does NOT maintain its own phase list -- a second list drifts from the
# canonical one, which is how the bloat phase went missing downstream.
#
# Usage: cd <target-repo> && bash <path-to-OliverCode>/scripts/qa/run-on-repo.sh
#
# Exit codes: propagated from full-qa-pass.sh (0 clean / 1 issues / 2 critical).

set -euo pipefail

REPO_ROOT="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QA_DIR="$REPO_ROOT/.qa-results"
mkdir -p "$QA_DIR"

echo "OliverCode QA Runner -- target: $(basename "$REPO_ROOT") ($REPO_ROOT)"
echo "Results: $QA_DIR/full-qa-pass.txt"
echo ""

set +e
bash "$SCRIPT_DIR/full-qa-pass.sh" --target "$REPO_ROOT" 2>&1 | tee "$QA_DIR/full-qa-pass.txt"
rc=${PIPESTATUS[0]}
set -e

echo ""
echo "Full output: $QA_DIR/full-qa-pass.txt"
exit "$rc"
