# Block commits containing personal identifiers: home paths, usernames, hostnames.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: PII scan..."

PII_PATTERNS=(
  '/Users/[A-Za-z0-9._-]+/'                              # macOS home directory paths
  '/home/[A-Za-z0-9._-]+/'                                # Linux home directory paths
  '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # Email addresses (any domain)
)

for pattern in "${PII_PATTERNS[@]}"; do
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        *.env.example|*mock*|tests/*|*/tests/*|*.test.*|*_test.*|*__tests__*|.gitignore|*.md|.githooks/pre-commit|core/templates/project/pre-commit|core/hooks/*) continue ;;
      esac
      # Strip known non-PII strings before matching. `git@github.com` is the SSH form npm
      # writes into package-lock.json for a git dependency, a protocol user on a public host,
      # so a lockfile with a git dependency stays committable.
      #
      # The strip works on the match, so anything else on the same line is still scanned.
      # Its class is positive and bounded to owner/repo, which is all a GitHub remote is,
      # so a separator after the repo name ends the strip. The `#<sha>` fragment is left in
      # place, since a tag name after it could hide an address. The left boundary stops a
      # longer word such as `notgit@github.com` from anchoring the exemption.
      if staged_content "$file" 2>/dev/null | sed -E 's#(^|[^A-Za-z0-9._%+-])git\+ssh://git@github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g; s#(^|[^A-Za-z0-9._%+-])git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g' | grep -nE -e "$pattern" >/dev/null; then
        staged_content "$file" 2>/dev/null | sed -E 's#(^|[^A-Za-z0-9._%+-])git\+ssh://git@github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g; s#(^|[^A-Za-z0-9._%+-])git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g' | grep -nE -e "$pattern"
        echo "  BLOCKED: $file contains PII matching pattern: $pattern"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    done <<< "$STAGED_FILES"
  fi
done

if [ $VIOLATIONS -gt 0 ]; then
  echo ""
  echo "=========================================="
  echo "COMMIT BLOCKED: $VIOLATIONS PII violation(s) found."
  echo "Use <workspace-root> placeholders for paths. Remove personal identifiers."
  echo "=========================================="
  exit 1
fi

echo "  Gate {{N}} passed."
