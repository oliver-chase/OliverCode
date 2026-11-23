# VERSION-FILES-1. VERSION and CHANGELOG.md belong to the daily cut (`olivercode version-cut`, docs/VERSIONING.md),
# so an ordinary commit cannot stage either one. The cut sets OLIVERCODE_VERSION_CUT=1 for its own commit.
# `validate.sh --tree` stages nothing, so the tree scan skips this gate.
if [ "${OLIVERCODE_SCAN_TREE:-}" != 1 ] && [ "${OLIVERCODE_VERSION_CUT:-}" != 1 ]; then
  VERSION_STAGED="$(printf '%s\n' "$STAGED_FILES" | grep -xE 'VERSION|CHANGELOG\.md' || true)"
  if [ -n "$VERSION_STAGED" ]; then
    echo "  BLOCKED: $(printf '%s' "$VERSION_STAGED" | tr '\n' ' ')belongs to the daily version cut and no ordinary commit edits it."
    echo "  Unstage it with: git restore --staged VERSION CHANGELOG.md"
    echo "  The cut writes both files once per day of activity (docs/VERSIONING.md)."
    exit 1
  fi
fi
