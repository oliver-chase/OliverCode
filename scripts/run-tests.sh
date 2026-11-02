#!/usr/bin/env bash
# Run the test suite from a clean clone of HEAD and report the commit it tested.
#
# Usage: scripts/run-tests.sh [repo_dir]     (default: the repo this script lives in)
#
# Uncommitted edits, another session's work in progress and untracked files are never read,
# because the suite runs in a fresh clone under a temporary HOME. The last line names the
# commit, so a failure points at a commit and not at a moving working tree.
set -u

repo="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || { echo "run-tests: $repo is not a git repo with a commit" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone -q --no-hardlinks --no-local "$repo" "$work/clone" || { echo "run-tests: clone failed" >&2; exit 2; }
git -C "$work/clone" checkout -q --detach "$sha" || { echo "run-tests: could not check out $sha" >&2; exit 2; }
mkdir "$work/home"

( cd "$work/clone" && HOME="$work/home" python3 -m unittest discover -b -s tests )
status=$?

if [[ "$status" -eq 0 ]]; then verdict="passed"; else verdict="FAILED"; fi
echo "run-tests: tests $verdict on commit $sha"
exit "$status"
