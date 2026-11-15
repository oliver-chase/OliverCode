#!/usr/bin/env bash
# validate.sh — Unified OliverCode validation entry point.
# Usage:
#   bash scripts/validate.sh                    — run every check
#   bash scripts/validate.sh --help             — list the options
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PRECOMMIT="${REPO_ROOT}/.githooks/pre-commit"

run_precommit() {
  if [[ -x "$PRECOMMIT" ]]; then
    echo "=== validate: running pre-commit gates over the whole tree ==="
    # The hook reads staged files by default, so on a clean tree it would scan nothing.
    OLIVERCODE_SCAN_TREE=1 bash "$PRECOMMIT"
    echo "=== validate: pre-commit passed ==="
  else
    echo "=== validate: pre-commit hook not found at $PRECOMMIT ==="
    exit 1
  fi
}

run_consistency() {
  # Three classes, each fail-closed:
  #  - doc-vs-code drift (skills index parity, gate-count claims)
  #  - unfalsifiable checks: a gate or script that cannot fail (scripts/lib/falsifiability_check.py)
  #  - hook drift: the pre-commit, pre-push and commit-msg hooks are built from core/hooks/, and a hand
  #    edit to a built hook fails (scripts/build-hooks.py)
  echo "=== validate: checking doc/code consistency ==="
  local out
  if ! out="$(python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.consistency_check import check_all as consistency
from lib.falsifiability_check import check_all as falsifiability
root = Path(sys.argv[2])
failures = consistency(root) + falsifiability(root)
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
' "${SCRIPT_DIR}" "${REPO_ROOT}")" || ! out="$(python3 "${SCRIPT_DIR}/build-hooks.py" --check)"; then
    printf '%s\n' "$out"
    echo "=== validate: consistency check FAILED ==="
    exit 1
  fi
  echo "=== validate: consistency passed ==="
}

run_hook_state() {
  # Hook enforcement fails OPEN -- an unset or broken core.hooksPath means git
  # runs no hooks and prints nothing. `olivercode conform` detects it, but nobody ran it
  # from a log anyone read, so a repo could sit ungoverned
  # for a week. Surfacing it here puts the signal where agents already look: CLAUDE.md
  # tells them to run validate.sh before every commit.
  #
  # Advisory, never fatal. A fork, a fresh clone, or a checkout with no fleet
  # registered has nothing to check and must still pass -- that property is what
  # rehearse-install.sh guards.
  #
  # --hooks-only checks only that git runs each repo's gates, the one fact this step exists for, so it never
  # reads a repo's files. A repo in a synced folder took over 30 minutes to count.
  echo "=== validate: checking fleet conformance ==="
  local out checked
  out="$(python3 "${SCRIPT_DIR}/olivercode" conform --offline --hooks-only 2>&1)" && local rc=0 || local rc=$?

  # Say which case it is: a fork with no fleet must not get a green line asserting a fleet was verified.
  checked="$(printf '%s\n' "$out" | sed -n 's/^Checked \([0-9]*\) repo.*/\1/p')"
  if [[ "$rc" -eq 0 && "${checked:-0}" -eq 0 ]]; then
    echo "  [SKIP] no fleet repos registered — nothing to check."
    echo "         Register repos in the registry's repo-profiles.json (see docs/SETUP.md)."
  elif [[ "$rc" -eq 0 ]]; then
    echo "  [OK] git runs the gates in all $checked registered repo(s). \`olivercode conform\` checks the rest of docs/CONTRACT.md"
  else
    printf '%s\n' "$out" | grep -E '^\s+\[FAIL\]|^         Fix:' || true
    echo "  [WARN] a repo above does not conform — the Fix line under each failure repairs it."
    echo "         A repo with stopped hooks is ungoverned: git runs no hooks and says nothing."
    echo "         Advisory here by design: a fork with no fleet must still pass."
  fi
}

run_reference_check() {
  # Internal reference integrity (markdown links + backtick repo paths).
  echo "=== validate: checking internal references ==="
  if ! bash "${SCRIPT_DIR}/link-check.sh" --quiet; then
    echo "=== validate: reference check FAILED ==="
    exit 1
  fi
  echo "=== validate: references passed ==="
}

run_duplication_check() {
  # Cross-doc content duplication (scripts/lib/duplication_check.py) -- the same rule
  # restated near-verbatim in two docs with no cross-reference between them. This
  # watches for duplication regrowing between manual reads.
  echo "=== validate: checking documentation duplication ==="
  local out
  if ! out="$(python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.duplication_check import check_all
failures = check_all(Path(sys.argv[2]))
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
' "${SCRIPT_DIR}" "${REPO_ROOT}")"; then
    printf '%s\n' "$out"
    echo "=== validate: duplication check FAILED ==="
    exit 1
  fi
  echo "=== validate: duplication check passed ==="
}

run_bloat_check() {
  # Bloat in one repo (default: this one). A repo holds current state only, so a tracked
  # archive-style directory or a file that marks itself historical fails. A docs-to-code
  # ratio past the threshold only warns, because it is a signal and not a defect.
  # Bash 3.2 compatible, with no grep -P and no mapfile.
  local dir="${1:-$REPO_ROOT}" ratio_max="0.60"
  echo "=== validate: checking for bloat and legacy files ==="
  if ! git -C "$dir" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "  [SKIP] $dir is not a git repository"
    return 0
  fi
  local hits=0 f n archive="" marked="" doc_loc=0 total_loc=0 ratio over
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    n=0
    [[ -f "$dir/$f" ]] && n=$(wc -l < "$dir/$f")
    total_loc=$((total_loc + n))
    case "$f" in *.md) doc_loc=$((doc_loc + n)) ;; esac
    if printf '%s\n' "$f" | grep -qiE '(^|/)(archive|archived|old|legacy)/'; then
      archive="$archive
  - $f"
    fi
    case "$f" in
      *.md)
        if head -5 "$dir/$f" 2>/dev/null | grep -qiE '^\**\s*(status:\s*)?(HISTORICAL|DEPRECATED|SUPERSEDED|ARCHIVED)\b'; then
          marked="$marked
  - $f"
        fi ;;
    esac
  done <<< "$(git -C "$dir" -c core.quotepath=false ls-files)"
  if [[ -n "$archive" ]]; then
    echo "  [FAIL] tracked files under archive-style directories (delete them, git history is the archive):$archive"
    hits=1
  fi
  if [[ -n "$marked" ]]; then
    echo "  [FAIL] files that mark themselves historical or deprecated (delete or update them):$marked"
    hits=1
  fi
  if [[ "$total_loc" -gt 0 ]]; then
    ratio=$(awk "BEGIN {printf \"%.2f\", $doc_loc / $total_loc}")
    over=$(awk "BEGIN {print ($ratio > $ratio_max) ? 1 : 0}")
    if [[ "$over" == "1" ]]; then
      echo "  [WARN] docs are $ratio of the repo's lines ($doc_loc of $total_loc; threshold $ratio_max) - run the audit skill on the docs"
    fi
  fi
  if [[ "$hits" -ne 0 ]]; then
    echo "=== validate: bloat check FAILED ==="
    return 1
  fi
  echo "=== validate: bloat check passed ==="
}

run_code_quality() {
  # Code quality in one repo (default: this one): TypeScript files over 400 lines, a
  # Python syntax error, and a scripts/lib module no test file mentions. The module
  # check matches the module's name, because tests here are named for the behavior they cover.
  local dir="${1:-$REPO_ROOT}" issues=0 f lines
  echo "=== validate: checking code quality ==="
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    lines=$(wc -l < "$f")
    if [[ "$lines" -gt 400 ]]; then
      echo "  [FAIL] $f has $lines lines (limit 400)"
      issues=$((issues + 1))
    fi
  done < <(git -C "$dir" -c core.quotepath=false ls-files -- '*.ts' '*.tsx' 2>/dev/null \
             | grep -v '\.test\.' | sed "s|^|$dir/|")
  if command -v python3 &>/dev/null; then
    while IFS= read -r f; do
      [[ -z "$f" ]] && continue
      if ! python3 -c 'import ast,sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$f" 2>/dev/null; then
        echo "  [FAIL] syntax error in $f"
        issues=$((issues + 1))
      fi
    done < <(git -C "$dir" -c core.quotepath=false ls-files -- '*.py' 2>/dev/null | sed "s|^|$dir/|")
  fi
  if [[ -d "$dir/scripts/lib" && -d "$dir/tests" ]]; then
    local module stem
    for module in "$dir"/scripts/lib/*.py; do
      [[ -e "$module" ]] || continue
      stem="$(basename "$module" .py)"
      [[ "$stem" == "__init__" ]] && continue
      if ! grep -qE "(^|[^A-Za-z0-9_])${stem}([^A-Za-z0-9_]|\$)" "$dir"/tests/*.py 2>/dev/null; then
        echo "  [FAIL] no test file mentions scripts/lib/${stem}.py"
        issues=$((issues + 1))
      fi
    done
  fi
  if [[ "$issues" -ne 0 ]]; then
    echo "=== validate: code quality FAILED ($issues issue(s)) ==="
    return 1
  fi
  echo "=== validate: code quality passed ==="
}

run_budget_check() {
  # docs/BUDGET.json caps the test count, doc words and skill words. A repo with no budget file has
  # nothing to check. The test runtime is measured by the audit skill's fleet_check.py --time.
  local dir="${1:-$REPO_ROOT}" out
  echo "=== validate: checking size budget ==="
  if [[ ! -f "$dir/docs/BUDGET.json" ]]; then
    echo "  [SKIP] no docs/BUDGET.json - nothing to check."
    return 0
  fi
  if ! out="$(python3 -c '
import sys
from pathlib import Path
import json
sys.path.insert(0, sys.argv[1])
import fleet_check as fc
repo = Path(sys.argv[2])
budget = json.loads((repo / fc.BUDGET_FILE).read_text(encoding="utf-8"))
measured = fc.measure(repo, fc.tracked(repo))
lines, over = fc.budget_lines(measured, budget)
for line in lines:
    if " is over the budget" in line:
        print("  [FAIL] " + line)
sys.exit(1 if over else 0)
' "${REPO_ROOT}/skills/audit/scripts" "$dir")"; then
    printf '%s\n' "$out"
    echo "=== validate: size budget FAILED (raise docs/BUDGET.json only with the story that needs the room) ==="
    return 1
  fi
  echo "=== validate: size budget passed ==="
}

run_smoke_tests() {
  # WARN-skip if tests/ doesn't exist or python3 is missing. Tests read the one
  # tracked shared/repo-profiles.json, so they pass identically everywhere.
  #
  # Python-only by design. A `node --test <dir>/*.mjs` block with no .mjs test present
  # exits 0 on the unmatched glob and reports success on zero tests. The one .mjs this repo ships
  # (core/templates/project/scripts/check-structure-contract.mjs) is a template that runs
  # in downstream repos. Re-add a runner deliberately if JS tests ever land.
  local tests_dir="${REPO_ROOT}/tests"
  if [[ ! -d "$tests_dir" ]]; then
    return 0
  fi
  echo "=== validate: running smoke tests ==="
  if command -v python3 &>/dev/null; then
    # Each test module runs in its own process, several at a time, because the suite spends
    # its time starting git and bash. -b buffers each test's stdout/stderr and replays it only
    # for failures: several tests exercise paths that print "[FAIL]" or "Error:" by design,
    # and unbuffered, a fully green run read like a broken build.
    local jobs log_dir module ran=0 n
    jobs="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"
    [[ "$jobs" -gt 6 ]] && jobs=6
    log_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$log_dir'" RETURN
    (cd "$tests_dir" && ls test_*.py | sed 's/\.py$//' | xargs -P "$jobs" -I{} \
      sh -c 'python3 -m unittest -b "$1" > "$2/$1.log" 2>&1 || echo "$1" >> "$2/failed"' _ {} "$log_dir")
    # Skill script tests.
    local skill_test
    for skill_test in "$REPO_ROOT"/skills/*/scripts/test_*.py; do
      [[ -e "$skill_test" ]] || continue
      printf '%s\n' "$skill_test"
    done | xargs -P "$jobs" -I{} \
      sh -c 'd="$(dirname "$1")"; m="$(basename "$1" .py)"; n="$(basename "$(dirname "$d")")-$m"; (cd "$d" && python3 -m unittest -b "$m") > "$2/$n.log" 2>&1 || echo "$n" >> "$2/failed"' _ {} "$log_dir"
    for module in "$log_dir"/*.log; do
      n="$(sed -n 's/^Ran \([0-9]*\) test.*/\1/p' "$module")"
      ran=$((ran + ${n:-0}))
    done
    if [[ -s "$log_dir/failed" ]]; then
      while IFS= read -r module; do
        echo "--- $module ---"
        cat "$log_dir/$module.log"
      done < "$log_dir/failed"
      echo "=== validate: python smoke tests FAILED ==="
      exit 1
    fi
    echo "  Ran $ran tests across $(ls "$log_dir"/*.log | wc -l | tr -d ' ') modules, all passed"
  else
    echo "  [WARN] python3 not found — skipping Python smoke tests"
  fi
  echo "=== validate: smoke tests passed ==="
}

main() {
  local mode="${1:-all}"
  if [[ "$mode" == "--tree" ]]; then
    export OLIVERCODE_SCAN_TREE=1
    mode=all
  fi

  case "$mode" in
    --help|-h)
      echo "Usage: bash scripts/validate.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  (no args)              Run pre-commit gates, doc/code consistency,"
      echo "                         reference integrity, bloat, code quality, doc duplication,"
      echo "                         smoke tests (tests/ and the skills' own script tests, if present)
                         and fleet conformance"
      echo "  --tree                 Run everything above, with the gates over every tracked file"
      echo "  --check-consistency    Run doc/code consistency checks only"
      echo "  --check-budget [dir]   Run the size budget check (docs/BUDGET.json) on this or another checkout"
      echo "  --check-repo <dir>     Run the bloat and code quality checks on another checkout"
      echo "  --rehearse [--clone]   Rehearse install and adoption in sandboxes (scripts/qa/rehearse-install.sh)"
      echo "  --help                 Show this help"
      ;;
    --check-consistency)
      run_consistency
      ;;
    --check-budget)
      run_budget_check "${2:-$REPO_ROOT}"
      ;;
    --check-repo)
      # The downstream governance gate: bloat and code quality for another checkout.
      local dir="${2:-}"
      if [[ -z "$dir" || ! -d "$dir" ]]; then
        echo "Usage: bash scripts/validate.sh --check-repo <dir>"
        exit 1
      fi
      local rc=0
      run_code_quality "$dir" || rc=1
      run_bloat_check "$dir" || rc=1
      exit "$rc"
      ;;
    --rehearse)
      exec bash "${SCRIPT_DIR}/qa/rehearse-install.sh" "${@:2}"
      ;;
    *)
      run_precommit
      run_consistency
      run_bloat_check || exit 1
      run_code_quality || exit 1
      run_reference_check
      run_duplication_check
      run_budget_check || exit 1
      run_smoke_tests
      run_hook_state
      ;;
  esac
}

main "$@"
