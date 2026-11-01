# Block commits referencing repos that no longer exist.
# Add project-specific deleted repo names here.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Deleted repo scan..."

DELETED_REPO_PATTERNS=(
  # Add deleted repo names here. Example:
  # 'old-project-name'
)

# A repo that is PUBLIC cannot list the names it must exclude in a tracked file:
# the denylist would publish the very strings the gate exists to keep out. An
# optional gitignored .private-patterns supplies them, one per line.
if [ -f .private-patterns ]; then
  while IFS= read -r _pattern; do
    case "$_pattern" in ''|\#*) continue ;; esac
    DELETED_REPO_PATTERNS+=("$_pattern")
  done < .private-patterns
fi

if [ ${#DELETED_REPO_PATTERNS[@]} -eq 0 ]; then
  # Say what actually happened. Announcing "passed" for a gate with an empty pattern
  # list implies stale repo references were checked for and none found, when nothing
  # was scanned at all -- a false assurance in the enforcement layer.
  echo "  Gate {{N}} skipped: no deleted-repo patterns configured (see DELETED_REPO_PATTERNS above)."
else
  # `while read` not `for` -- unquoted $STAGED_FILES word-splits on filenames with spaces.
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      for bad_path in "${DELETED_REPO_PATTERNS[@]}"; do
        if grep -n "$bad_path" "$file" 2>/dev/null; then
          echo "  BLOCKED: $file references deleted path: $bad_path"
          exit 1
        fi
      done
    done <<< "$STAGED_FILES"
  fi
  echo "  Gate {{N}} passed."
fi
