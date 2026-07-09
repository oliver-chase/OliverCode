#!/usr/bin/env bash
# ─── Bloat & Legacy Check ────────────────────────────────────────────────
# Deterministic bloat detection for any fleet repo. A rule without a gate
# regresses (verified: 105 inline styles, an 8.7k-LOC archive dir) — this
# makes bloat mechanical instead of a judgment call during audits.
#
# Checks (WARN by default; --strict exits nonzero on any hit):
#   1. archive/ directories — the fleet convention is REMOVE, don't
#      archive (git history is the archive).
#   2. docs-to-code LOC ratio past threshold (default 0.60) — docs
#      sprawl signal, not a hard failure.
#   3. tracked files self-marked as historical/deprecated/superseded —
#      each is a validate-then-delete candidate.
#
# Usage: bash check-bloat.sh [--target <dir>] [--strict] [--ratio N.NN]
# Bash 3.2 / BSD-grep compatible (no grep -P, no mapfile).
set -euo pipefail

TARGET_DIR="$(pwd)"
STRICT=0
RATIO_MAX="0.60"
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET_DIR="$2"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    --ratio) RATIO_MAX="$2"; shift 2 ;;
    *) shift ;;
  esac
done

cd "$TARGET_DIR"
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "bloat: SKIP (not a git repo: $TARGET_DIR)"
  exit 0
fi

HITS=0

# 1. Archive directories (tracked only)
# git ls-files output is newline-delimited (filenames may still contain
# spaces) -- iterate with `while read` and quote "$f", never `xargs` or
# unquoted `for f in $(...)`, both of which word-split on internal spaces.
# core.quotepath=false so non-ASCII filenames (em-dash etc) aren't octal-escaped.
ARCHIVE_DIRS=$(git -c core.quotepath=false ls-files | grep -iE '(^|/)(archive|archived|old|legacy)/' | sed -E 's#/(.*)##' | sort -u || true)
ARCHIVE_FILES=0
ARCHIVE_LOC=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  ARCHIVE_FILES=$((ARCHIVE_FILES + 1))
  n=$(wc -l < "$f" 2>/dev/null || echo 0)
  ARCHIVE_LOC=$((ARCHIVE_LOC + n))
done <<< "$(git -c core.quotepath=false ls-files | grep -iE '(^|/)(archive|archived|old|legacy)/' || true)"
if [ "$ARCHIVE_FILES" -gt 0 ]; then
  echo "bloat: archive-style directories hold $ARCHIVE_FILES tracked file(s), $ARCHIVE_LOC LOC -- convention is remove-don't-archive (validate expiry, delete; git history is the archive)"
  HITS=$((HITS + 1))
fi

# 2. Docs-to-code ratio
DOC_LOC=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  n=$(wc -l < "$f" 2>/dev/null || echo 0)
  DOC_LOC=$((DOC_LOC + n))
done <<< "$(git -c core.quotepath=false ls-files '*.md')"
TOTAL_LOC=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  n=$(wc -l < "$f" 2>/dev/null || echo 0)
  TOTAL_LOC=$((TOTAL_LOC + n))
done <<< "$(git -c core.quotepath=false ls-files)"
if [ "$TOTAL_LOC" -gt 0 ]; then
  RATIO=$(awk "BEGIN {printf \"%.2f\", $DOC_LOC / $TOTAL_LOC}")
  OVER=$(awk "BEGIN {print ($RATIO > $RATIO_MAX) ? 1 : 0}")
  if [ "$OVER" = "1" ]; then
    echo "bloat: docs are ${RATIO} of the repo's LOC ($DOC_LOC of $TOTAL_LOC; threshold $RATIO_MAX) -- consider a docs-reality-audit / history trim"
    HITS=$((HITS + 1))
  fi
fi

# 3. Self-declared-historical tracked files (first 5 lines only -- a
#    header marker, not a prose mention)
SELF_MARKED=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if head -5 "$f" 2>/dev/null | grep -qiE '^\**\s*(status:\s*)?(HISTORICAL|DEPRECATED|SUPERSEDED|ARCHIVED)\b'; then
    SELF_MARKED="$SELF_MARKED
$f"
  fi
done <<< "$(git -c core.quotepath=false ls-files '*.md')"
if [ -n "$SELF_MARKED" ]; then
  echo "bloat: self-marked historical/deprecated files (validate-then-delete candidates):"
  echo "$SELF_MARKED" | while IFS= read -r f; do [ -n "$f" ] && echo "  - $f"; done
  HITS=$((HITS + 1))
fi

if [ "$HITS" -eq 0 ]; then
  echo "bloat: PASS (no archive dirs, docs ratio ok, no self-marked legacy)"
  exit 0
fi
echo "bloat: $HITS finding group(s)"
if [ "$STRICT" = "1" ]; then exit 1; fi
exit 0
