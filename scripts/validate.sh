#!/usr/bin/env bash
# validate.sh — Unified OliverCode validation entry point.
# Usage:
#   bash scripts/validate.sh                    — run every check
#   bash scripts/validate.sh --quick FILE...    — run changed-file checks during development
#   bash scripts/validate.sh --help             — list the options
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PRECOMMIT="${REPO_ROOT}/.githooks/pre-commit"

run_precommit() {
  # "$@": files changed against origin's default branch, from a round check (#1142). Given files, the hook
  # scans only those; empty for a full run, which scans the whole tree, as `olivercode land` always runs it.
  if [[ -x "$PRECOMMIT" ]]; then
    if [[ $# -gt 0 ]]; then
      echo "=== validate: running pre-commit gates over the changed files ==="
      OLIVERCODE_SCAN_FILES="$(printf '%s\n' "$@")" bash "$PRECOMMIT"
    else
      echo "=== validate: running pre-commit gates over the whole tree ==="
      # The hook reads staged files by default, so on a clean tree it would scan nothing.
      OLIVERCODE_SCAN_TREE=1 bash "$PRECOMMIT"
    fi
    echo "=== validate: pre-commit passed ==="
  else
    echo "=== validate: pre-commit hook not found at $PRECOMMIT ==="
    exit 1
  fi
}

run_build_hooks() {
  # The pre-commit, pre-push and commit-msg hooks are built from core/hooks/ and untracked
  # (HOOK-OUTPUTS-1), so they are built before the gates, checks and tests that read them.
  python3 "${SCRIPT_DIR}/build-hooks.py" || { echo "=== validate: hook build FAILED ==="; exit 1; }
}

run_consistency() {
  # Fail-closed check that no tracked file names a fleet repo (scripts/lib/fleet_name_check.py)
  echo "=== validate: checking fleet names ==="
  local out
  if ! out="$(python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.fleet_name_check import check_all as fleet_names
root = Path(sys.argv[2])
failures = fleet_names(root)
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
' "${SCRIPT_DIR}" "${REPO_ROOT}")"; then
    printf '%s\n' "$out"
    echo "=== validate: fleet name check FAILED ==="
    exit 1
  fi
  echo "=== validate: fleet names passed ==="
}

run_hook_state() {
  # Hook enforcement fails open: an unset or broken core.hooksPath means git runs no hooks and prints
  # nothing. This step reports it where agents already look, since CLAUDE.md has them run validate.sh
  # before every commit.
  # Advisory, never fatal. A fork, a fresh clone, or a checkout with no fleet
  # registered has nothing to check and must still pass -- that property is what
  # rehearse-install.sh guards.
  # --hooks-only checks only that git runs each repo's gates, the one fact this step exists for, so it never
  # reads a repo's files, which in a synced folder can take many minutes.
  echo "=== validate: checking fleet conformance ==="
  local out checked
  out="$(python3 "${SCRIPT_DIR}/olivercode" conform --offline --hooks-only 2>&1)" && local rc=0 || local rc=$?

  checked="$(printf '%s\n' "$out" | sed -n 's/^Checked \([0-9]*\) repo.*/\1/p')"
  if [[ "$rc" -eq 0 && "${checked:-0}" -eq 0 ]]; then
    echo "  [SKIP] no fleet repos registered — nothing to check."
    echo "         Register repos in the registry's repo-profiles.json (see docs/SETUP.md)."
  elif [[ "$rc" -eq 0 ]]; then
    echo "  [OK] git runs the gates in all $checked registered repo(s). `olivercode conform` checks the rest of docs/CONTRACT.md"
  else
    printf '%s\n' "$out" | grep -E '^\s+\[FAIL\]|^         Fix:' || true
    echo "  [WARN] a repo above does not conform — the Fix line under each failure repairs it."
    echo "         A repo with stopped hooks is ungoverned: git runs no hooks and says nothing."
    echo "         Advisory here by design: a fork with no fleet must still pass."
  fi
}

run_docs_check() {
  echo "=== validate: checking docs against code ==="
  if ! python3 "${REPO_ROOT}/core/templates/project/scripts/docs_check.py" "${REPO_ROOT}"; then
    echo "=== validate: docs check FAILED ==="
    exit 1
  fi
}

run_limits_check() {
  echo "=== validate: checking size limits ==="
  python3 "${SCRIPT_DIR}/olivercode" limits check
}

run_reference_check() {
  echo "=== validate: checking internal references ==="
  if ! bash "${SCRIPT_DIR}/link-check.sh" --quiet; then
    echo "=== validate: reference check FAILED ==="
    exit 1
  fi
  echo "=== validate: references passed ==="
}

run_bloat_check() {
  python3 "${SCRIPT_DIR}/lib/repo_checks.py" bloat "${1:-$REPO_ROOT}"
}

run_code_quality() {
  python3 "${SCRIPT_DIR}/lib/repo_checks.py" quality "${1:-$REPO_ROOT}"
}

run_queue_bypass() {
  python3 "${SCRIPT_DIR}/lib/queue_bypass.py" "$REPO_ROOT"
}

run_smoke_tests() {
  # "$@": files changed against origin's default branch. Empty for a full run, which every
  # `olivercode land` always runs.
  [[ -d "${REPO_ROOT}/tests" ]] || return 0
  echo "=== validate: running smoke tests ==="
  if [[ $# -gt 0 ]]; then
    python3 "${SCRIPT_DIR}/lib/smoke_runner.py" "$REPO_ROOT" --changed "$@" || exit 1
  else
    python3 "${SCRIPT_DIR}/lib/smoke_runner.py" "$REPO_ROOT" || exit 1
  fi
  echo "=== validate: smoke tests passed ==="
}

GATES=(precommit fleet bloat quality refs docs limits bypass smoke hookstate)

run_gate() {
  local name="$1"
  shift
  case "$name" in
    precommit) run_precommit "$@" ;;
    fleet) run_consistency ;;
    bloat) run_bloat_check || exit 1 ;;
    quality) run_code_quality || exit 1 ;;
    refs) run_reference_check ;;
    docs) run_docs_check ;;
    limits) run_limits_check ;;
    bypass) run_queue_bypass ;;
    smoke) run_smoke_tests "$@" ;;
    hookstate) run_hook_state ;;
    *) echo "validate: no gate named '$name'" >&2; exit 2 ;;
  esac
}

run_gates() {
  local args=() gate
  for gate in "${GATES[@]}"; do
    args+=("${gate}=$(printf '%q ' bash "${SCRIPT_DIR}/validate.sh" --gate "$gate")")
  done
  python3 "${SCRIPT_DIR}/lib/validate_gates.py" "${args[@]}"
}

round_notice() {
  local ran=" precommit bypass smoke " left=() gate
  for gate in "${GATES[@]}"; do
    [[ "$ran" == *" $gate " ]] || left+=("$gate")
  done
  echo "=== validate: round check ran:${ran% } ==="
  echo "=== validate: round check left out: ${left[*]}. They run when the story lands. ==="
}

run_round_gates() {
  local args=() gate
  round_notice
  for gate in precommit bypass smoke; do
    args+=("${gate}=$(printf '%q ' bash "${SCRIPT_DIR}/validate.sh" --gate "$gate" "$@")")
  done
  python3 "${SCRIPT_DIR}/lib/validate_gates.py" "${args[@]}"
}

main() {
  local mode="${1:-all}"

  case "$mode" in
    --help|-h)
      echo "Usage: bash scripts/validate.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  (no args)              Run every validation gate; this is the full pre-merge check"
      echo "  --tree                 Same as no args"
      echo "  --quick FILE...        Fast changed-file check: pre-commit, relevant smoke tests and queue bypass"
      echo "  --round FILE...        Internal per-round form of --quick"
      echo "  --round-notice         Print the gates a round runs and the ones it leaves to the landing"
      echo "  --check-consistency    Run the fleet name check only"
      echo "  --check-repo <dir>     Run the bloat and code quality checks on another checkout"
      echo "  --rehearse [--clone]   Rehearse install and adoption in sandboxes (scripts/qa/rehearse-install.sh)"
      echo "  --help                 Show this help"
      echo ""
      echo "Use --quick while editing; run the full suite before merge or landing."
      ;;
    --gate)
      shift
      run_gate "$@"
      ;;
    --round-notice)
      round_notice
      ;;
    --quick)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Usage: bash scripts/validate.sh --quick FILE..." >&2
        echo "Pass at least one changed path; use --tree for full validation." >&2
        exit 2
      fi
      run_build_hooks
      run_round_gates "$@"
      ;;
    --round)
      shift
      run_build_hooks
      run_round_gates "$@"
      ;;
    --check-consistency)
      run_build_hooks
      run_consistency
      ;;
    --check-repo)
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
    all|--tree)
      local tree
      tree="$(python3 "${SCRIPT_DIR}/olivercode" validated snapshot)" || exit 1
      run_build_hooks
      run_gates
      python3 "${SCRIPT_DIR}/olivercode" validated record "$tree"
      ;;
    *)
      echo "Unknown option: $mode" >&2
      echo "Usage: bash scripts/validate.sh [--help | --tree | --quick FILE... | --gate NAME | --check-consistency | --check-repo <dir> | --rehearse]" >&2
      exit 2
      ;;
  esac
}

case "${1:-}" in --help|-h|--gate) VALIDATE_QUEUE_SLOT="${VALIDATE_QUEUE_SLOT:-none}" ;; esac

VALIDATE_QUEUE_BIN="${SCRIPT_DIR}/lib/validate_queue.py"
VALIDATE_QUEUE_BIN="${VALIDATE_QUEUE_BIN:-$HOME/.local/bin/validate-queue}"
if [[ -z "${VALIDATE_QUEUE_SLOT:-}" ]]; then
  if [[ -x "$VALIDATE_QUEUE_BIN" ]]; then
    VALIDATE_QUEUE_SLOT="$("$VALIDATE_QUEUE_BIN" acquire --pid $$ --label "$(basename "${REPO_ROOT:-$PWD}")" || true)"
    export VALIDATE_QUEUE_SLOT="${VALIDATE_QUEUE_SLOT:-none}"
    [[ -n "$(trap -p EXIT)" ]] || trap '"$VALIDATE_QUEUE_BIN" release "$VALIDATE_QUEUE_SLOT" >/dev/null 2>&1 || true' EXIT
  else
    echo "validate: no validate-queue helper at $VALIDATE_QUEUE_BIN, running unqueued" >&2
  fi
fi

main "$@"
