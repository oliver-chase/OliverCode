#!/usr/bin/env bash
# ─── Full QA Pass (Automated) ─────────────────────────────────────────────
# Combines code quality, docs cohesion, and workflow status checks into a
# single automated sweep. No LLM calls — pure static analysis.
#
# Usage: bash scripts/qa/full-qa-pass.sh [--verbose] [--target <dir>]
#
# This delegates entirely to check-code-quality.sh, check-docs-cohesion.sh,
# check-workflow-status.sh, and check-bloat.sh — the four canonical checkers — and sums
# their exit codes. It does not reimplement their checks; a divergent inline
# copy here would just drift from the canonical logic again.
#
# Exit codes:
#   0 - All checks pass
#   1 - Issues found (non-critical)
#   2 - Critical issues found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERBOSE=false
TARGET_DIR="${REPO_ROOT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=true; shift ;;
    --target) TARGET_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 3 ;;
  esac
done

TOTAL_ISSUES=0
CRITICAL_ISSUES=0
START_TIME=$(date +%s)

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         FULL QA PASS (Automated)                        ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo "Target: $TARGET_DIR"
echo ""

# run_phase <label> <script> [extra args...]
# Runs a canonical checker against $TARGET_DIR, prints its output, and
# folds its exit code (0 ok / 1 issues / 2 critical / 3 script error) into
# the running totals. Never lets a checker's nonzero exit kill this script.
run_phase() {
  local label="$1" script="$2"
  shift 2
  echo "╔══ $label ═══════════════════════════════════╗"
  set +e
  bash "$SCRIPT_DIR/$script" --target "$TARGET_DIR" "$@"
  local rc=$?
  set -e
  echo ""
  case "$rc" in
    0) : ;;
    1) TOTAL_ISSUES=$((TOTAL_ISSUES + 1)) ;;
    2) TOTAL_ISSUES=$((TOTAL_ISSUES + 1)); CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1)) ;;
    *) echo "  ERROR: $label exited $rc (script error)"
       TOTAL_ISSUES=$((TOTAL_ISSUES + 1)); CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1)) ;;
  esac
  return 0
}

if [ "$VERBOSE" = true ]; then
  run_phase "Phase 1: Code Quality" "check-code-quality.sh" --verbose
else
  run_phase "Phase 1: Code Quality" "check-code-quality.sh"
fi
run_phase "Phase 2: Documentation Cohesion" "check-docs-cohesion.sh"
run_phase "Phase 3: Workflow Status" "check-workflow-status.sh"
run_phase "Phase 4: Bloat & Legacy" "check-bloat.sh"

# ─── Summary ─────────────────────────────────────────────────────────────
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         SUMMARY                                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo "Duration: ${DURATION}s"
echo "Phases with issues: $TOTAL_ISSUES / 4 (critical: $CRITICAL_ISSUES)"
echo ""

if [ "$CRITICAL_ISSUES" -gt 0 ]; then
  echo "CRITICAL ISSUES FOUND — review required before proceeding."
  exit 2
elif [ "$TOTAL_ISSUES" -gt 0 ]; then
  echo "Issues found — review above for details."
  exit 1
else
  echo "All checks passed. Repository is in good health."
  exit 0
fi
