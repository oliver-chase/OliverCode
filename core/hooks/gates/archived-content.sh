# A repo holds current state only. A superseded file gets deleted or replaced, never
# parked in an Archive/ folder or beside its replacement as "-old" -- git already
# holds every past version, so a second copy on disk is a copy nothing keeps in sync,
# and the reader cannot tell which one is live.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Archived-content scan..."

# Matched as a whole PATH SEGMENT, never a substring: a file legitimately titled
# "Legacy Modernization Intelligence" is prose about legacy systems, not an archive.
ARCHIVE_SEGMENTS='^(_?[Aa]rchive[ds]?|[Ll]egacy|[Dd]eprecated|[Oo]utdated|_?[Bb]ackups?|[Oo]ld)$'
# Suffixes that mark a file as a superseded copy of its neighbour.
# "copy" is deliberately NOT here. In many repos copy means written copy -- "Slide
# Copy", "Website Services Copy" -- so matching it blocked 30-plus live files on
# the first run.
ARCHIVE_SUFFIX='(\.bak|~|[ _-]old|[ _-]backup|[ _-]deprecated|[ _-]superseded)(\.[A-Za-z0-9]+)?$'

# A repo with permanent records in an archive-named folder declares them in its own
# optional .githooks/pre-commit.local (GATE-LOCAL-1). The gate asks that file about one
# path, with empty stdin, only when it is about to block. Exit status 10 exempts the path;
# any other status keeps the block, so a local hook that does not know this argument
# cannot exempt anything by accident.
is_archive_exempt() {
  [ -x "$HOOK_DIR/pre-commit.local" ] || return 1
  local rc=0
  "$HOOK_DIR/pre-commit.local" archive-exempt "$1" </dev/null >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 10 ]
}

if [ -n "$STAGED_FILES" ]; then
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    # Any directory segment that names an archive.
    printf '%s\n' "$file" | tr '/' '\n' | grep -qE "$ARCHIVE_SEGMENTS" && ! is_archive_exempt "$file" && {
      echo "  BLOCKED: $file sits under a directory that names an archive."
      echo "  This repo holds current state only. Delete the superseded copy --"
      echo "  git history is the archive. If it is genuinely still live, rename the"
      echo "  directory to say what it holds."
      exit 1
    }

    # A filename marked as a superseded copy.
    if printf '%s\n' "${file##*/}" | grep -qE "$ARCHIVE_SUFFIX" && ! is_archive_exempt "$file"; then
      echo "  BLOCKED: $file is named as a superseded copy."
      echo "  Replace the file it supersedes and never commit both; git keeps"
      echo "  the previous version."
      exit 1
    fi
  done <<< "$STAGED_FILES"
fi

echo "  Gate {{N}} passed."
