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
  #
  # Advisory, never fatal. A fork, a fresh clone, or a checkout with no fleet
  # registered has nothing to check and must still pass -- that property is what
  # rehearse-install.sh guards.
  #
  # --hooks-only checks only that git runs each repo's gates, the one fact this step exists for, so it never
  # reads a repo's files, which in a synced folder can take many minutes.
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

run_docs_check() {
  # The docs match the code: launcher commands, the gates table and the skills index against README.md and docs/.
  echo "=== validate: checking docs against code ==="
  if ! python3 "${REPO_ROOT}/core/templates/project/scripts/docs_check.py" "${REPO_ROOT}"; then
    echo "=== validate: docs check FAILED ==="
    exit 1
  fi
}

run_limits_check() {
  # The size ceiling only warns (#879): the check prints the count and never fails the run.
  echo "=== validate: checking size limits ==="
  python3 "${SCRIPT_DIR}/olivercode" limits check || true
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

run_bloat_check() {
  # Bloat in one repo (default: this one). A repo holds current state only, so a tracked
  # archive-style directory or a file that marks itself historical fails. A docs-to-code
  # ratio past the threshold only warns, because it is a signal and not a defect.
  # One Python pass over one `git ls-files` listing (scripts/lib/repo_checks.py).
  python3 "${SCRIPT_DIR}/lib/repo_checks.py" bloat "${1:-$REPO_ROOT}"
}

run_code_quality() {
  # Code quality in one repo (default: this one): TypeScript files over 400 lines, a
  # Python syntax error, and a scripts/lib module no test file mentions. The module
  # check matches the module's name, because tests here are named for the behavior they cover.
  python3 "${SCRIPT_DIR}/lib/repo_checks.py" quality "${1:-$REPO_ROOT}"
}

run_queue_bypass() {
  # Every caller reaches validation through this script, whose queue block takes the slot. A tracked script that starts the
  # test suite or a slotless copy of validate.sh around the queue fails here (scripts/lib/queue_bypass.py).
  python3 "${SCRIPT_DIR}/lib/queue_bypass.py" "$REPO_ROOT"
}

run_smoke_tests() {
  # Skipped when tests/ does not exist. Tests read the one tracked shared/repo-profiles.json, so they pass identically everywhere.
  #
  # Python-only by design. A `node --test <dir>/*.mjs` block with no .mjs test present
  # exits 0 on the unmatched glob and reports success on zero tests. The one .mjs this repo ships
  # (core/templates/project/scripts/check-structure-contract.mjs) is a template that runs
  # in downstream repos. Re-add a runner deliberately if JS tests ever land.
  [[ -d "${REPO_ROOT}/tests" ]] || return 0
  echo "=== validate: running smoke tests ==="
  # Each test module runs in its own process, several at a time (scripts/lib/smoke_runner.py), with failures replayed in full.
  python3 "${SCRIPT_DIR}/lib/smoke_runner.py" "$REPO_ROOT" || exit 1
  echo "=== validate: smoke tests passed ==="
}

# The gates that share no state, in the order their output is replayed. Each is `bash validate.sh --gate NAME`.
GATES=(precommit fleet bloat quality refs docs limits bypass smoke hookstate)

run_gate() {
  case "$1" in
    precommit) run_precommit ;;
    fleet) run_consistency ;;
    bloat) run_bloat_check || exit 1 ;;
    quality) run_code_quality || exit 1 ;;
    refs) run_reference_check ;;
    docs) run_docs_check ;;
    limits) run_limits_check ;;
    bypass) run_queue_bypass ;;
    smoke) run_smoke_tests ;;
    hookstate) run_hook_state ;;
    *) echo "validate: no gate named '$1'" >&2; exit 2 ;;
  esac
}

run_gates() {
  # The gates run inside this run's one slot, at most one per core at once, each writing to its own file. A line prints as each
  # gate starts and finishes, and the output replays in order, so the log reads as one sequential run and any failing gate fails
  # the run. A run past its time budget stops and names the gate still running (scripts/lib/validate_gates.py).
  local args=() gate
  for gate in "${GATES[@]}"; do
    args+=("${gate}=$(printf '%q ' bash "${SCRIPT_DIR}/validate.sh" --gate "$gate")")
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
      echo "  (no args)              Run pre-commit gates, fleet names, reference integrity, bloat,"
      echo "                         code quality, the docs and size limit checks, the queue bypass check, smoke tests (tests/ and the"
      echo "                         skills' own script tests, if present) and fleet conformance, in"
      echo "                         parallel inside one queue slot, printing each gate as it starts and finishes"
      echo "                         OLIVERCODE_VALIDATE_TIMEOUT (seconds) is the run's budget, OLIVERCODE_VALIDATE_RETRIES"
      echo "                         reruns stopped gates and OLIVERCODE_VALIDATE_GATES caps the gates at once (default: cores);"
      echo "                         OLIVERCODE_VALIDATE_JOBS sets the smoke test parallelism"
      echo "  --tree                 Same as no args (the pre-commit gates always scan every tracked file)"
      echo "  --check-consistency    Run the fleet name check only"
      echo "  --check-repo <dir>     Run the bloat and code quality checks on another checkout"
      echo "  --rehearse [--clone]   Rehearse install and adoption in sandboxes (scripts/qa/rehearse-install.sh)"
      echo "  --help                 Show this help"
      ;;
    --gate)
      run_gate "${2:-}"
      ;;
    --check-consistency)
      run_build_hooks
      run_consistency
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
    all|--tree)
      # The tree is snapshotted before the gates start, so an edit made during the run is never stamped as validated.
      local tree
      tree="$(python3 "${SCRIPT_DIR}/olivercode" validated snapshot)" || exit 1
      run_build_hooks
      run_gates
      python3 "${SCRIPT_DIR}/olivercode" validated record "$tree"
      ;;
    *)
      echo "Unknown option: $mode" >&2
      echo "Usage: bash scripts/validate.sh [--help | --tree | --gate NAME | --check-consistency | --check-repo <dir> | --rehearse]" >&2
      exit 2
      ;;
  esac
}

# Help and a single gate started by a run that holds its slot already take none of their own.
case "${1:-}" in --help|-h|--gate) VALIDATE_QUEUE_SLOT="${VALIDATE_QUEUE_SLOT:-none}" ;; esac

# The validation queue block is the one the fleet shares (core/templates/project/scripts/validate-queue.snippet.sh), pointed at this checkout's helper.
VALIDATE_QUEUE_BIN="${SCRIPT_DIR}/lib/validate_queue.py"
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

main "$@"
