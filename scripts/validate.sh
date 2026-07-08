#!/usr/bin/env bash
# validate.sh — Unified OliverCode validation entry point.
# Token-policy checking now lives inside .githooks/pre-commit itself (Gate 8),
# so run_precommit() below covers it — no separate call needed.
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

run_smoke_tests() {
  # OC-10: optional -- WARN-skip if tests/ doesn't exist or a runtime is missing.
  # Tests read only the tracked shared/repo-profiles.example.json, never local/
  # (gitignored, absent on forks), so they must pass identically everywhere.
  local tests_dir="${REPO_ROOT}/tests"
  if [[ ! -d "$tests_dir" ]]; then
    return 0
  fi
  echo "=== validate: running smoke tests ==="
  if command -v python3 &>/dev/null; then
    if ! python3 -m unittest discover "$tests_dir"; then
      echo "=== validate: python smoke tests FAILED ==="
      exit 1
    fi
  else
    echo "  [WARN] python3 not found — skipping Python smoke tests"
  fi
  if command -v node &>/dev/null; then
    if ! node --test "$tests_dir"/*.mjs; then
      echo "=== validate: node smoke tests FAILED ==="
      exit 1
    fi
  else
    echo "  [WARN] node not found — skipping Node smoke tests"
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
      [ $# -gt 0 ] && shift  # consume repo if given; remaining args are paths
      # (was `shift 2`, which aborted under `set -e` when no repo arg was passed)
      echo "=== validate: testing token-policy path filtering for $repo ==="
      python3 "$SCRIPT_DIR/apply-token-policy.py" "$repo" "$@" 2>&1 || echo "  (no paths provided — pipe paths via stdin)"
      ;;
    --help|-h)
      echo "Usage: bash scripts/validate.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  (no args)              Run pre-commit gates (Gate 8 incl.) + smoke tests (tests/, if present)"
      echo "  --evidence <file>      Run pre-commit + gatekeeper"
      echo "  --gatekeeper-only <file>  Run gatekeeper only"
      echo "  --target-repo <repo-root> [args...]"
      echo "                         Run <repo-root>/scripts/validate-repo.sh if it exists"
      echo "                         (repo-local validation hook convention), else skip"
      echo "  --check-token-policy   Run token policy check only"
      echo "  --check-paths <repo>   Test token-policy path filtering for a repo (pipe paths via stdin)"
      echo "  --help                 Show this help"
      ;;
    *)
      run_precommit
      run_smoke_tests
      ;;
  esac
}

main "$@"
