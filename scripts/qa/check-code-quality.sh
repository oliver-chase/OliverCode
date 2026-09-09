#!/usr/bin/env bash
# ─── QA Code Quality Check ────────────────────────────────────────────────
# Static analysis, no LLM calls: oversized files, missing test coverage per lib
# module, Python syntax, and (with --verbose) magic numbers and non-standard throws.
#
# File-size and syntax checks are aimed at the TypeScript/Next.js fleet repos. The
# test-coverage map (section 2) checks both layouts: one-directory-per-module (TS
# fleet) and flat scripts/lib/*.py (this repo) -- GATE-FALSIFIABILITY-1's own lesson
# was that a check silently inert for the repo it runs against is worse than no
# check, because it reports clean either way.
#
# Usage: bash scripts/qa/check-code-quality.sh [--target <dir>] [--verbose]
#
# Options:
#   --target <dir>   Scan a specific directory instead of the whole repo
#   --verbose        Also run the two slower greps (magic numbers, bare throws)
#
# Exit codes:
#   0 - All checks pass
#   1 - Issues found
#   3 - Script error (unknown option)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_DIR="${REPO_ROOT}"
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET_DIR="$2"; shift 2 ;;
    --verbose) VERBOSE=true; shift ;;
    *) echo "Unknown option: $1"; exit 3 ;;
  esac
done

cd "$REPO_ROOT"

# Results tracking
TOTAL_ISSUES=0

echo "=== QA: Code Quality Check ==="
echo "Target: $TARGET_DIR"
echo ""

# ─── 1. Check file sizes (functions too long) ────────────────────────────
echo "--- 1. File Size Check (> 400 lines) ---"
LARGE_FILES=$(find "$TARGET_DIR" -name '*.ts' -o -name '*.tsx' 2>/dev/null |\
  grep -v node_modules | grep -v '\.next' | grep -v '\.test\.' | grep -v '/\.claude/' |\
  while read -r f; do
    lines=$(wc -l < "$f" 2>/dev/null || echo 0)
    if [ "$lines" -gt 400 ]; then
      echo "  $lines lines  $f"
    fi
  done || true)
if [ -n "$LARGE_FILES" ]; then
  echo "$LARGE_FILES" | head -20
  TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
else
  echo "  No large files found."
fi
echo ""

# ─── 2. Test coverage map ────────────────────────────────────────────────
echo "--- 2. Test Coverage Map ---"
if [ -d "$TARGET_DIR/tests" ]; then
  MISSING_TESTS=0
  # TS/Next.js fleet layout: one directory per lib module.
  if [ -d "$TARGET_DIR/lib" ]; then
    for module in "$TARGET_DIR/lib/"*/; do
      [ -e "$module" ] || continue
      module_name=$(basename "$module")
      test_file=$(find "$TARGET_DIR/tests" -name "*${module_name}*" -o -name "*${module_name}*.test.*" 2>/dev/null | head -1)
      if [ -z "$test_file" ]; then
        ts_count=$(find "$module" -maxdepth 1 -name '*.ts' 2>/dev/null | wc -l)
        if [ "$ts_count" -gt 0 ]; then
          echo "  MISSING: No test file for lib/$module_name/ ($ts_count source files)"
          MISSING_TESTS=$((MISSING_TESTS + 1))
        fi
      fi
    done
  fi
  # Python flat-file layout (COVERAGE-MAP-1): one .py file per module, no subdirs --
  # the directory-only glob above silently matches nothing here. Test files here are
  # named by behavior, not by module (test_falsifiability.py tests
  # falsifiability_check.py), so filename substring matching is not reliable; every
  # test loads its module with `REPO_ROOT / "scripts" / "lib" / "<module>.py"`
  # (importlib.util.spec_from_file_location), so grep for that literal instead.
  if [ -d "$TARGET_DIR/scripts/lib" ]; then
    for pyfile in "$TARGET_DIR/scripts/lib/"*.py; do
      [ -e "$pyfile" ] || continue
      module_name=$(basename "$pyfile")
      [ "$module_name" = "__init__.py" ] && continue
      if ! grep -ql "\"${module_name}\"" "$TARGET_DIR/tests/"*.py 2>/dev/null; then
        echo "  MISSING: No test file for scripts/lib/${module_name}"
        MISSING_TESTS=$((MISSING_TESTS + 1))
      fi
    done
  fi
  TOTAL_ISSUES=$((TOTAL_ISSUES + MISSING_TESTS))
  if [ "$MISSING_TESTS" -eq 0 ]; then
    echo "  All lib modules have test coverage."
  fi
else
  echo "  No tests/ directory found."
fi
echo ""

# ─── 3. Check for magic numbers (literals in code) ───────────────────────
echo "--- 3. Magic Number Check ---"
if [ "$VERBOSE" = true ]; then
  MAGIC=$(grep -rn "if.*[0-9]\{4,\}" "$TARGET_DIR" --include='*.ts' 2>/dev/null |\
    grep -v node_modules | grep -v '\.next' | grep -v '\.test\.' | grep -v "new Date\|\.json\|timeout\|port\|limit\|offset\|maxResults\|MAX_\|MIN_\|DEFAULT_" |\
    grep -v "status\|Math\.\|86400\|3600\|1000\|1024" | head -20 || true)
  if [ -n "$MAGIC" ]; then
    echo "  Suspicious magic numbers:"
    echo "$MAGIC"
    TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
  else
    echo "  No obvious magic numbers."
  fi
else
  echo "  Skipped (use --verbose to run)."
fi
echo ""

# ─── 4. Missing error handling (bare throws) ──────────────────────────────
echo "--- 4. Missing Error Handling Check ---"
if [ "$VERBOSE" = true ]; then
  BARE_THROWS=$(grep -rn "throw new" "$TARGET_DIR" --include='*.ts' 2>/dev/null |\
    grep -v node_modules | grep -v '\.next' | grep -v '\.test\.' | grep -v "Error\|TypeError\|RangeError" | head -10 || true)
  if [ -n "$BARE_THROWS" ]; then
    echo "  Non-standard error throws:"
    echo "$BARE_THROWS"
    TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
  else
    echo "  No non-standard error throws."
  fi
else
  echo "  Skipped (use --verbose to run)."
fi
echo ""

# ─── 5. Python-specific checks (if running on a Python repo) ────────
echo "--- 5. Python Syntax Check ---"
PYTHON_FILES=$(find "$TARGET_DIR" -name '*.py' -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' 2>/dev/null | head -5)
if [ -n "$PYTHON_FILES" ]; then
  echo "  Python files detected — running syntax checks..."
  PYTHON_ERRORS=0
  while IFS= read -r -d '' pyfile; do
    if python3 -m py_compile "$pyfile" 2>/dev/null; then
      :
    else
      echo "  SYNTAX ERROR in $pyfile"
      PYTHON_ERRORS=$((PYTHON_ERRORS + 1))
    fi
  done < <(find "$TARGET_DIR" -name '*.py' -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' -print0 2>/dev/null)
  if [ "$PYTHON_ERRORS" -gt 0 ]; then
    echo "  $PYTHON_ERRORS Python file(s) with syntax errors."
    TOTAL_ISSUES=$((TOTAL_ISSUES + PYTHON_ERRORS))
  else
    echo "  All Python files pass syntax check."
  fi
else
  echo "  No Python files found in target."
fi
echo ""

# ─── Summary ──────────────────────────────────────────────────────────────
echo "=== Summary ==="
echo "Total issues found: $TOTAL_ISSUES"
echo ""

if [ "$TOTAL_ISSUES" -gt 0 ]; then
  exit 1
else
  echo "All checks passed."
  exit 0
fi
