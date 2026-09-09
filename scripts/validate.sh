#!/usr/bin/env bash
# validate.sh — Unified OliverCode validation entry point.
# Token-policy checking is Gate 8 of .githooks/pre-commit, so run_precommit()
# below covers it — no separate call needed.
# Usage:
#   bash scripts/validate.sh                    — run pre-commit gates (incl. token policy)
#   bash scripts/validate.sh --evidence <file>  — run pre-commit + gatekeeper
#   bash scripts/validate.sh --gatekeeper-only <file>  — run gatekeeper only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GATEKEEPER="${SCRIPT_DIR}/orchestration-gatekeeper.py"
PRECOMMIT="${REPO_ROOT}/.githooks/pre-commit"

run_precommit() {
  if [[ -x "$PRECOMMIT" ]]; then
    echo "=== validate: running pre-commit gates ==="
    bash "$PRECOMMIT"
    echo "=== validate: pre-commit passed ==="
  else
    echo "=== validate: pre-commit hook not found at $PRECOMMIT ==="
    exit 1
  fi
}

run_token_policy_check() {
  echo "=== validate: checking token policy ==="
  if python3 "$GATEKEEPER" --check-token-policy; then
    echo "=== validate: token policy passed ==="
  else
    exit 1
  fi
}

run_consistency() {
  # Two classes, both fail-closed, both learned from real defects here:
  #  - doc-vs-code drift (skills index parity, gate-count claims, gate integrity)
  #  - unfalsifiable checks: a gate or script that cannot fail. A string of defects in this
  #    repo shared that shape, and none was visible from output, because the output
  #    always said PASS. See scripts/lib/falsifiability_check.py.
  #  - hook drift: the three pre-commit hooks implement the same gates and nothing
  #    compared them. Two carried broken doc pointers in the message shown at the
  #    moment a developer is blocked. See scripts/lib/hook_drift_check.py.
  echo "=== validate: checking doc/code consistency ==="
  local out
  if ! out="$(python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${SCRIPT_DIR}')
from lib.consistency_check import check_all as consistency
from lib.falsifiability_check import check_all as falsifiability
from lib.hook_drift_check import check_all as hook_drift
root = Path('${REPO_ROOT}')
failures = consistency(root) + falsifiability(root) + hook_drift(root)
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
")"; then
    printf '%s\n' "$out"
    echo "=== validate: consistency check FAILED ==="
    exit 1
  fi
  echo "=== validate: consistency passed ==="
}

run_hook_state() {
  # Hook enforcement fails OPEN -- an unset or broken core.hooksPath means git
  # runs no hooks and prints nothing. `olivercode health` detects it, but health ran
  # only from a weekly cron into a log nobody read, so a repo could sit ungoverned
  # for a week. Surfacing it here puts the signal where agents already look: CLAUDE.md
  # tells them to run validate.sh before every commit.
  #
  # Advisory, never fatal. A fork, a fresh clone, or a checkout with no fleet
  # registered has nothing to check and must still pass -- that property is what
  # check-fork-usable.sh guards.
  echo "=== validate: checking fleet hook state ==="
  local out registered
  out="$(python3 "${SCRIPT_DIR}/olivercode" health 2>&1)" && local rc=0 || local rc=$?

  # "every registered repo has working hooks" was printed even when the number of
  # registered repos was ZERO -- a fork with no fleet got a green line asserting a
  # fleet was verified. Say which case it is.
  registered="$(printf '%s\n' "$out" | grep -cE '^\s+\[(OK|FAIL|WARN)\] [^ ]+: ' || true)"
  if [[ "$rc" -eq 0 && "$registered" -eq 0 ]]; then
    echo "  [SKIP] no fleet repos registered — nothing to check."
    echo "         Register repos in local/repo-profiles.json (see docs/ADOPTING.md)."
  elif [[ "$rc" -eq 0 ]]; then
    echo "  [OK] all $registered registered repo(s) have working hooks"
  else
    printf '%s\n' "$out" | grep -E '^\s+\[FAIL\]' || true
    echo "  [WARN] a repo above is not fully governed — 'olivercode sync-hooks' repairs it."
    echo "         Enforcement fails open: git runs no hooks and says nothing."
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
  # restated near-verbatim in two docs with no cross-reference between them. A full
  # manual read found this four times in a repo already through one dedup audit; this
  # is what watches for it regrowing between reads.
  echo "=== validate: checking documentation duplication ==="
  local out
  if ! out="$(python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${SCRIPT_DIR}')
from lib.duplication_check import check_all
failures = check_all(Path('${REPO_ROOT}'))
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
")"; then
    printf '%s\n' "$out"
    echo "=== validate: duplication check FAILED ==="
    exit 1
  fi
  echo "=== validate: duplication check passed ==="
}

run_comment_budget() {
  # CODE_INTENT_STANDARD §1 was instruction text until this gate; see the script
  # header for why block length is fatal and density is not. Runs the template
  # this repo ships to the fleet, so OliverCode is held to the rule it publishes.
  echo "=== validate: checking comment budget ==="
  if ! command -v node &>/dev/null; then
    echo "  [WARN] node not found — skipping comment-budget check"
    return 0
  fi
  if ! node "${REPO_ROOT}/core/templates/project/scripts/check-comment-budget.mjs" --quiet; then
    echo "=== validate: comment budget FAILED ==="
    exit 1
  fi

  # CODE_INTENT_STANDARD §4. The template copy is run directly, as above: a second
  # copy in scripts/ would be the drift this repo exists to prevent.
  echo "=== validate: checking decision ledger ==="
  if ! node "${REPO_ROOT}/core/templates/project/scripts/check-decisions.mjs" > /dev/null; then
    node "${REPO_ROOT}/core/templates/project/scripts/check-decisions.mjs" | grep "FAIL:"
    echo "=== validate: decision ledger FAILED ==="
    exit 1
  fi
}

run_smoke_tests() {
  # WARN-skip if tests/ doesn't exist or python3 is missing. Tests read only the
  # tracked shared/repo-profiles.example.json, never local/ (gitignored, absent on
  # forks), so they pass identically everywhere.
  #
  # Python-only by design. A `node --test <dir>/*.mjs` block used to run here; with no
  # .mjs test present the unmatched glob makes node exit 0, so it reported success on
  # zero tests -- a false green. The one .mjs this repo ships
  # (core/templates/project/scripts/check-structure-contract.mjs) is a template that runs
  # in downstream repos, not here. Re-add a runner deliberately if JS tests ever land.
  local tests_dir="${REPO_ROOT}/tests"
  if [[ ! -d "$tests_dir" ]]; then
    return 0
  fi
  echo "=== validate: running smoke tests ==="
  if command -v python3 &>/dev/null; then
    # -b buffers each test's stdout/stderr and replays it only for failures. Several
    # tests exercise paths that print "[FAIL]" or "Error:" by design; unbuffered, a
    # fully green run scrolled those past the operator and read like a broken build.
    if ! python3 -m unittest discover -b -s "$tests_dir"; then
      echo "=== validate: python smoke tests FAILED ==="
      exit 1
    fi
  else
    echo "  [WARN] python3 not found — skipping Python smoke tests"
  fi
  echo "=== validate: smoke tests passed ==="
}

run_gatekeeper() {
  local evidence_file="$1"
  local repo_name="${2:-}"
  local task_type="${3:-write_code}"

  if [[ ! -f "$GATEKEEPER" ]]; then
    echo "=== validate: gatekeeper not found at $GATEKEEPER ==="
    exit 1
  fi

  # Auto-detect repo name from git remote if not provided
  if [[ -z "$repo_name" ]]; then
    repo_name=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null | sed 's/.*\///; s/\.git$//' || echo "unknown")
  fi

  echo "=== validate: running gatekeeper (repo=$repo_name, type=$task_type) ==="
  python3 "$GATEKEEPER" --repo "$repo_name" --task-type "$task_type" --evidence-file "$evidence_file"
}

main() {
  local mode="${1:-all}"

  case "$mode" in
    --target-repo)
      # Generic cross-repo validation: exec the target repo's own validation
      # hook if it declares one, by convention (<target-repo>/scripts/validate-repo.sh).
      # Skips gracefully if the target repo has no such hook — OliverCode carries
      # no repo-specific enforcement itself (see docs/BACKLOG.md D2).
      local repo_root="${2:-}"
      shift 2 || true

      if [[ -z "$repo_root" ]]; then
        echo "Usage: bash scripts/validate.sh --target-repo <repo-root> [args passed through to validate-repo.sh]"
        exit 1
      fi
      if [[ ! -d "$repo_root" ]]; then
        echo "=== validate: target repo not found: $repo_root ==="
        exit 1
      fi

      local hook="$repo_root/scripts/validate-repo.sh"
      if [[ -x "$hook" ]]; then
        echo "=== validate: running $repo_root/scripts/validate-repo.sh ==="
        bash "$hook" "$@"
      else
        echo "=== validate: no scripts/validate-repo.sh in $repo_root — skipping (nothing to check) ==="
      fi
      ;;

    --evidence)
      local evidence_file="${2:-}"
      if [[ -z "$evidence_file" ]]; then
        echo "Usage: bash scripts/validate.sh --evidence <file> [repo] [task-type]"
        exit 1
      fi
      run_precommit
      run_gatekeeper "$evidence_file" "${3:-}" "${4:-write_code}"
      ;;
    --gatekeeper-only)
      local evidence_file="${2:-}"
      if [[ -z "$evidence_file" ]]; then
        echo "Usage: bash scripts/validate.sh --gatekeeper-only <file> [repo] [task-type]"
        exit 1
      fi
      run_gatekeeper "$evidence_file" "${3:-}" "${4:-write_code}"
      ;;
    --check-token-policy)
      run_token_policy_check
      ;;
    --check-paths)
      shift  # consume --check-paths
      local repo="${1:-olivercode}"
      # Guard the shift: a bare `shift 2` aborts under `set -e` with no repo arg.
      [ $# -gt 0 ] && shift  # consume repo if given; remaining args are paths
      echo "=== validate: testing token-policy path filtering for $repo ==="
      python3 "$SCRIPT_DIR/apply-token-policy.py" "$repo" "$@" 2>&1 || echo "  (no paths provided — pipe paths via stdin)"
      ;;
    --help|-h)
      echo "Usage: bash scripts/validate.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  (no args)              Run pre-commit gates (Gate 8 incl.), doc/code consistency,"
      echo "                         reference integrity, and smoke tests (tests/, if present)"
      echo "  --evidence <file>      Run pre-commit + gatekeeper"
      echo "  --gatekeeper-only <file>  Run gatekeeper only"
      echo "  --target-repo <repo-root> [args...]"
      echo "                         Run <repo-root>/scripts/validate-repo.sh if it exists"
      echo "                         (repo-local validation hook convention), else skip"
      echo "  --check-consistency    Run doc/code consistency checks only"
      echo "  --check-token-policy   Run token policy check only"
      echo "  --check-paths <repo>   Test token-policy path filtering for a repo (pipe paths via stdin)"
      echo "  --help                 Show this help"
      ;;
    --check-consistency)
      run_consistency
      ;;
    *)
      run_precommit
      run_consistency
      run_reference_check
      run_duplication_check
      run_comment_budget
      run_smoke_tests
      run_hook_state
      ;;
  esac
}

main "$@"
