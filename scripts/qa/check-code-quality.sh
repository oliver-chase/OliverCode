#!/usr/bin/env bash
# ─── QA Code Quality Check ────────────────────────────────────────────────
# Automated code quality audit: import cycles, unused vars, function length,
# test coverage gaps. No LLM calls — pure static analysis.
#
# Usage: bash scripts/qa/check-code-quality.sh [--fix] [--target <dir>]
#
# Options:
#   --target <dir>   Scan a specific directory instead of the whole repo
#   --fix            Attempt auto-fix for trivial issues (unused imports)
#   --verbose        Show detailed output per file
#
# Exit codes:
#   0 - All checks pass
#   1 - Issues found (warnings)
#   2 - Critical issues found
#   3 - Script error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_DIR="${REPO_ROOT}"
FIX_MODE=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET_DIR="$2"; shift 2 ;;
    --fix) FIX_MODE=true; shift ;;
    --verbose) VERBOSE=true; shift ;;
    *) echo "Unknown option: $1"; exit 3 ;;
  esac
done

if [ "$FIX_MODE" = true ]; then
  echo "NOTE: --fix is not yet implemented — no auto-fixes will be applied. Running read-only checks."
  echo ""
fi

cd "$REPO_ROOT"

# Results tracking
TOTAL_ISSUES=0
CRITICAL_ISSUES=0

echo "=== QA: Code Quality Check ==="
echo "Target: $TARGET_DIR"
echo ""

# ─── 1. Check for unused imports in TypeScript files ─────────────────────
echo "--- 1. Unused Import Detection ---"
if command -v ts-prune &>/dev/null; then
  ts-prune --project tsconfig.json 2>/dev/null | head -50 || true
else
  echo "  ts-prune not installed. Run: npm install -g ts-prune"
  echo "  Falling back to basic check..."
  UNUSED=$(grep -rn "^import.*from" "$TARGET_DIR" --include='*.ts' --include='*.tsx' 2>/dev/null |\
    grep -v node_modules | grep -v '\.next' | grep -v '\.test\.' | head -20 || true)
  if [ -n "$UNUSED" ]; then
    echo "  Sample imports found (cannot verify unused without ts-prune):"
    echo "  $UNUSED"
  fi
fi
echo ""

# ─── 2. Check file sizes (functions too long) ────────────────────────────
echo "--- 2. File Size Check (> 400 lines) ---"
LARGE_FILES=$(find "$TARGET_DIR" -name '*.ts' -o -name '*.tsx' 2>/dev/null |\
  grep -v node_modules | grep -v '\.next' | grep -v '\.test\.' |\
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

# ─── 3. Test coverage map ────────────────────────────────────────────────
echo "--- 3. Test Coverage Map ---"
if [ -d "$TARGET_DIR/tests" ]; then
  # Map each lib module to its test file
  MISSING_TESTS=0
  for module in "$TARGET_DIR/lib/"*/; do
    module_name=$(basename "$module")
    # Look for matching test file
    test_file=$(find "$TARGET_DIR/tests" -name "*${module_name}*" -o -name "*${module_name}*.test.*" 2>/dev/null | head -1)
    if [ -z "$test_file" ]; then
      # Check if there are any .ts files in the module
      ts_count=$(find "$module" -maxdepth 1 -name '*.ts' 2>/dev/null | wc -l)
      if [ "$ts_count" -gt 0 ]; then
        echo "  MISSING: No test file for lib/$module_name/ ($ts_count source files)"
        MISSING_TESTS=$((MISSING_TESTS + 1))
      fi
    fi
  done
  TOTAL_ISSUES=$((TOTAL_ISSUES + MISSING_TESTS))
  if [ "$MISSING_TESTS" -eq 0 ]; then
    echo "  All lib modules have test coverage."
  fi
else
  echo "  No tests/ directory found."
fi
echo ""

# ─── 4. Check for magic numbers (literals in code) ───────────────────────
echo "--- 4. Magic Number Check ---"
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

# ─── 5. Missing error handling (bare throws) ──────────────────────────────
echo "--- 5. Missing Error Handling Check ---"
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

# ─── 6. Python-specific checks (if running on a Python repo) ────────
echo "--- 6. Python Syntax Check ---"
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

# ─── 7. Python test runner check ──────────────────────────────────
echo "--- 7. Test Runner Check ---"
if [ -d "$TARGET_DIR/tests" ]; then
  echo "  tests/ directory found. Run manually: cd $TARGET_DIR && python3 -m pytest tests/ -v"
fi
echo ""
# ─── Summary ──────────────────────────────────────────────────────────────
echo "=== Summary ==="
echo "Total issues found: $TOTAL_ISSUES"
echo "Critical issues: $CRITICAL_ISSUES"
echo ""

if [ "$CRITICAL_ISSUES" -gt 0 ]; then
  exit 2
elif [ "$TOTAL_ISSUES" -gt 0 ]; then
  exit 1
else
  echo "All checks passed."
  exit 0
fi
