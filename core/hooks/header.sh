#!/usr/bin/env bash
# Pre-commit hook: {{VARIANT}}. Block = no commit.
# Generated from a shared hook source, and `olivercode sync-hooks` replaces a hand edit made here.
# Change a gate at that source.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
# Git sets GIT_DIR when it runs a hook in a linked worktree, and `git -C <dir>` then takes
# <dir> as the work tree, so every repo path would point inside .githooks. Git runs a hook
# from the work-tree root, so in that case the root comes from the current directory.
if [ -n "${GIT_DIR:-}" ]; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
else
  REPO_ROOT="$(git -C "$HOOK_DIR" rev-parse --show-toplevel)"
fi
# A commit checks only what it stages, so a clean commit says nothing about the rest of the tree.
# `validate.sh --tree` sets this to run every gate over every tracked file.
if [ "${OLIVERCODE_SCAN_TREE:-}" = 1 ]; then
  STAGED_FILES=$(git -C "$REPO_ROOT" -c core.quotepath=off ls-files)
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
# gate_list FILE KEY prints each string in the JSON array KEY of the staged FILE.
gate_list() {
  git show ":$1" 2>/dev/null | tr '\n' ' ' \
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
