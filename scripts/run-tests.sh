#!/usr/bin/env bash
# Run the test suite from a clean clone of HEAD and report the commit it tested.
#
# Usage: scripts/run-tests.sh [repo_dir]     (default: the repo this script lives in)
#
# Every test module runs in its own process (scripts/lib/smoke_runner.py, as validate.sh does), because two modules share the
# name test_sweep and one process cannot import both (#770).
#
# Uncommitted edits, another session's work in progress and untracked files are never read,
# because the suite runs in a fresh clone under a temporary HOME. The last line names the
# commit, so a failure points at a commit and not at a moving working tree.
#
# The run starts at once and writes nothing in this machine's ~/.olivercode, so a record or log there cannot change a verdict.
set -u

repo="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || { echo "run-tests: $repo is not a git repo with a commit" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone -q --no-hardlinks --no-local "$repo" "$work/clone" || { echo "run-tests: clone failed" >&2; exit 2; }
git -C "$work/clone" checkout -q --detach "$sha" || { echo "run-tests: could not check out $sha" >&2; exit 2; }
mkdir "$work/home"

smoke_runner="$(cd "$(dirname "$0")" && pwd)/lib/smoke_runner.py"
env -u OLIVERCODE_HOME HOME="$work/home" python3 "$smoke_runner" "$work/clone"
status=$?

if [[ "$status" -eq 0 ]]; then verdict="passed"; else verdict="FAILED"; fi
echo "run-tests: tests $verdict on commit $sha"
exit "$status"
