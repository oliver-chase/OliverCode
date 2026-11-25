#!/usr/bin/env bash
# Pre-commit hook: {{VARIANT}}. Block = no commit.
# Generated from a shared hook source, and `olivercode sync-hooks` replaces a hand edit made here.
# Change a gate at that source.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
# Git runs a client-side hook with the working directory already at the top of the working
# tree that triggered it, worktree included, so the repo root never depends on where this
# script sits. core.hooksPath can now be one machine-wide folder outside every repo (#1154),
# so HOOK_DIR is no longer inside the repo for every caller.
REPO_ROOT="$(git rev-parse --show-toplevel)"
# A commit checks only what it stages, so a clean commit says nothing about the rest of the tree.
# `validate.sh --tree` sets this to run every gate over every tracked file.
# `validate.sh --round` sets OLIVERCODE_SCAN_FILES instead, to a round check's changed files (#1142), so the
# gates scan just those instead of the whole tree.
if [ "${OLIVERCODE_SCAN_TREE:-}" = 1 ]; then
  STAGED_FILES=$(git -C "$REPO_ROOT" -c core.quotepath=off ls-files)
elif [ -n "${OLIVERCODE_SCAN_FILES:-}" ]; then
  STAGED_FILES="$OLIVERCODE_SCAN_FILES"
else
  STAGED_FILES=$(git -C "$REPO_ROOT" -c core.quotepath=off diff --cached --name-only --no-renames --diff-filter=ACM)
fi
cd "$REPO_ROOT"

# Git prints a name with an accent or an em dash quoted unless core.quotepath is off, and a gate that
# read the quoted name would never open the file. A gate also reads what the commit records, which is
# the staged content, because the working copy can hold something else by the time the commit lands.
# A path that is not in the index falls back to the working copy.
# Every staged file is written once into a snapshot folder, so the gates read plain files and never start
# one `git show` per file per gate.
OC_SNAPSHOT="$(mktemp -d "${TMPDIR:-/tmp}/oc-staged.XXXXXX")"
printf '%s\n' "$STAGED_FILES" | sed '/^$/d' \
  | git -C "$REPO_ROOT" checkout-index --prefix="$OC_SNAPSHOT/" --stdin >/dev/null 2>&1 || true
staged_content() {
  if [ -f "$OC_SNAPSHOT/$1" ] && [ ! -L "$OC_SNAPSHOT/$1" ]; then
    cat -- "$OC_SNAPSHOT/$1"
  else
    git -C "$REPO_ROOT" show ":$1" 2>/dev/null || cat -- "$1"
  fi
}
# TEXT_FILES is STAGED_FILES minus every binary file, so a gate that reads content never runs sed or grep
# over a PNG, a font or a PDF. One `git grep -I` over the index lists the text files with git's own test
# (a NUL in the first 8000 bytes, or a binary attribute), and the staged list is cut to those. A gate that
# reads only names or sizes keeps using STAGED_FILES, so a staged binary still counts there.
TEXT_FILES=""
if [ -n "$STAGED_FILES" ]; then
  TEXT_FILES=$(git -C "$REPO_ROOT" -c core.quotepath=off grep --cached -I --name-only -e '' 2>/dev/null \
    | grep -Fxf - <(printf '%s\n' "$STAGED_FILES") || true)
fi
# gate_list FILE KEY prints each string in the JSON array KEY of FILE as HEAD holds it.
gate_list() {
  # It reads the config from HEAD, because a commit that edits the config would otherwise exempt itself.
  git show "HEAD:$1" 2>/dev/null | tr '\n' ' ' \
    | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
    | grep -o '"[^"]*"' | sed 's/^"//; s/"$//' || true
}
# matches_glob PATH GLOBS succeeds when PATH matches one of the newline-separated GLOBS.
matches_glob() {
  local glob
  while IFS= read -r glob; do
    [ -n "$glob" ] || continue
    case "$1" in $glob) return 0 ;; esac
  done <<< "$2"
  return 1
}

VIOLATIONS=0
