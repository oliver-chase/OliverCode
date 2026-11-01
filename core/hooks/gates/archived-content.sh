# A repo holds current state only. A superseded file gets deleted or replaced, never
# parked in an Archive/ folder or beside its replacement as "-old" -- git already
# holds every past version, so a second copy on disk is a copy nothing keeps in sync,
# and the reader cannot tell which one is live.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Archived-content scan..."

# Matched as a whole PATH SEGMENT, never a substring: a file legitimately titled
# "Legacy Modernization Intelligence" is prose about legacy systems, not an archive.
ARCHIVE_SEGMENTS='^(_?[Aa]rchive[ds]?|[Ll]egacy|[Dd]eprecated|[Oo]utdated|_?[Bb]ackups?|[Oo]ld)$'
# Suffixes that mark a file as a superseded copy of its neighbour.
# "copy" is deliberately NOT here. In this vault copy means written copy -- "Slide
# Copy", "Website Services Copy" -- so matching it blocked 30-plus live files on
# the first run.
ARCHIVE_SUFFIX='(\.bak|~|[ _-]old|[ _-]backup|[ _-]deprecated|[ _-]superseded)(\.[A-Za-z0-9]+)?$'

# Deliberate exceptions. Each is a permanent record by decision, not drift.
#   Past To Dos/  - the weekly-task archive the vault's CLAUDE.md calls permanent
is_archive_exempt() {
  case "$1" in
    *"Past To Dos/"*) return 0 ;;
  esac
  return 1
}

if [ -n "$STAGED_FILES" ]; then
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    is_archive_exempt "$file" && continue

    # Any directory segment that names an archive.
    printf '%s\n' "$file" | tr '/' '\n' | grep -qE "$ARCHIVE_SEGMENTS" && {
      echo "  BLOCKED: $file sits under a directory that names an archive."
      echo "  This repo holds current state only. Delete the superseded copy --"
      echo "  git history is the archive. If it is genuinely still live, rename the"
      echo "  directory to say what it holds."
      exit 1
    }

    # A filename marked as a superseded copy.
    if printf '%s\n' "${file##*/}" | grep -qE "$ARCHIVE_SUFFIX"; then
      echo "  BLOCKED: $file is named as a superseded copy."
      echo "  Replace the file it supersedes and never commit both; git keeps"
      echo "  the previous version."
      exit 1
    fi
  done <<< "$STAGED_FILES"
fi

echo "  Gate {{N}} passed."
