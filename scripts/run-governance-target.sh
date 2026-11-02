#!/usr/bin/env bash
# ─── Governance Gate — Target Repo Wrapper ────────────────────────────────
# Thin CI wrapper around `validate.sh --check-repo`, which runs the bloat and code quality checks.
# Invoked by core/templates/project/.github/workflows/olivercode-governance.yml
# from within a downstream repo's checkout, after this OliverCode repo has been
# checked out to `.olivercode/` inside that checkout:
#
#   .olivercode/scripts/run-governance-target.sh --target-repo "$GITHUB_WORKSPACE" \
#     --repo-name "<repo-name>"
#
# Deliberately does not reimplement the checks — it points validate.sh at
# the target repo and propagates its exit code.

set -euo pipefail

TARGET_REPO=""
REPO_NAME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target-repo)
      TARGET_REPO="$2"
      shift 2
      ;;
    --repo-name)
      REPO_NAME="$2"
      shift 2
      ;;
    *)
      echo "run-governance-target.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$TARGET_REPO" ]; then
  echo "run-governance-target.sh: --target-repo is required" >&2
  exit 2
fi

if [ ! -d "$TARGET_REPO" ]; then
  echo "run-governance-target.sh: target repo not found: $TARGET_REPO" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="${REPO_NAME:-$(basename "$TARGET_REPO")}"

echo "OliverCode governance gate — target: $LABEL ($TARGET_REPO)"

exec bash "$SCRIPT_DIR/validate.sh" --check-repo "$TARGET_REPO"
