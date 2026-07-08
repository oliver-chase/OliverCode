#!/usr/bin/env bash
# ─── Run Full QA Pass on a Target Repo ───────────────────────────────────
# Wrapper that runs the full QA automation against any OliverCode project.
# Called from the target repo's root.
#
# Usage: bash <(curl -s https://raw.githubusercontent.com/oliver-chase/OliverCode/main/scripts/qa/run-on-repo.sh)
#
# This script:
# 1. Clones/runs the QA scripts from OliverCode (or finds them locally)
# 2. Exports results to .qa-results/ directory in the target repo
# 3. Summarizes findings for human review

set -euo pipefail

# Target repo is wherever this script is invoked from (per the contract above).
REPO_ROOT="$(pwd)"
# The check scripts themselves live alongside this script in OliverCode.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || pwd)"
QA_DIR="$REPO_ROOT/.qa-results"
mkdir -p "$QA_DIR"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     OliverCode QA Runner                                 ║"
echo "║     Target: $(basename "$REPO_ROOT")"
echo "╚═══════════════════════════════════════════════════════════╝"
echo "Results: $QA_DIR"
echo ""

# Find OliverCode scripts (this script's own directory first)
OLIVERCODE_SCRIPTS=""
for candidate in \
  "$SCRIPT_DIR" \
  "$REPO_ROOT/../OliverCode/scripts/qa" \
  "$REPO_ROOT/../../OliverCode/scripts/qa" \
  "../OliverCode/scripts/qa"; do
  if [ -d "$candidate" ]; then
    OLIVERCODE_SCRIPTS="$candidate"
    break
  fi
done

if [ -z "$OLIVERCODE_SCRIPTS" ]; then
  echo "ERROR: Cannot find OliverCode QA scripts."
  echo "Clone OliverCode to a sibling directory or run from within the OliverCode repo."
  exit 1
fi

echo "Using QA scripts from: $OLIVERCODE_SCRIPTS"
echo ""

FAILED=0

# ─── Phase 1: Code Quality ────────────────────────────────────────────────
echo ">>> Phase 1: Code Quality..."
if bash "$OLIVERCODE_SCRIPTS/check-code-quality.sh" --target "$REPO_ROOT" 2>&1 | tee "$QA_DIR/phase1-code-quality.txt" | tail -20; then
  echo "  Phase 1 passed."
else
  echo "  Phase 1 found issues (see $QA_DIR/phase1-code-quality.txt)"
  FAILED=1
fi
echo ""

# ─── Phase 2: Docs Cohesion ───────────────────────────────────────────────
echo ">>> Phase 2: Documentation Cohesion..."
if bash "$OLIVERCODE_SCRIPTS/check-docs-cohesion.sh" --target "$REPO_ROOT" 2>&1 | tee "$QA_DIR/phase2-docs-cohesion.txt" | tail -20; then
  echo "  Phase 2 passed."
else
  echo "  Phase 2 found issues (see $QA_DIR/phase2-docs-cohesion.txt)"
  FAILED=1
fi
echo ""

# ─── Phase 3: Workflow Status ─────────────────────────────────────────────
echo ">>> Phase 3: Workflow Status..."
if bash "$OLIVERCODE_SCRIPTS/check-workflow-status.sh" --target "$REPO_ROOT" 2>&1 | tee "$QA_DIR/phase3-workflow-status.txt" | tail -20; then
  echo "  Phase 3 passed."
else
  echo "  Phase 3 found issues (see $QA_DIR/phase3-workflow-status.txt)"
  FAILED=1
fi
echo ""

# ─── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     QA Results Summary                                  ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo "Results saved to: $QA_DIR"
echo ""
echo "Files:"
ls -la "$QA_DIR/"
echo ""
echo "Next: Review the issue files above, then run the relevant"
echo "LLM prompt for qualitative fixes where needed."
echo "  - QA-15 for code quality fixes"
echo "  - QA-16 for documentation fixes"
echo "  - QA-17 for workflow status fixes"
echo "  - QA-ALL for combined pass"

if [ "$FAILED" -eq 1 ]; then
  exit 1
fi
