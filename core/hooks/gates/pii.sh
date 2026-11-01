# Block commits containing personal identifiers: home paths, usernames, hostnames.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: PII scan..."

PII_PATTERNS=(
  '/Users/[a-z]+/'                              # macOS home directory paths
  '/home/[a-z]+/'                               # Linux home directory paths
  '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # Email addresses (any domain)
)

for pattern in "${PII_PATTERNS[@]}"; do
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        *.env.example|*mock*|tests/*|*/tests/*|*.test.*|*_test.*|*__tests__*|.gitignore|*.md|.githooks/pre-commit|core/templates/project/pre-commit|core/hooks/*|config/contracts/planning-doc-governance.json) continue ;;
      esac
      # Strip known non-PII strings before matching. `git@github.com` is the
      # SSH form npm writes into package-lock.json "resolved" entries for a git
      # dependency — a protocol user on a public host, not a person's address.
      # Without this, adding any git dependency makes the lockfile permanently
      # uncommittable, and a gate that blocks a correct commit is one people
      # learn to pass with --no-verify.
      #
      # Stripped at MATCH level, not line level. Filtering whole grep output
      # lines let anything sharing a line with an exempt string escape EVERY
      # pattern, including /Users/ home paths that have nothing to do with
      # lockfiles.
      #
      # The class is POSITIVE and bounded to owner/repo, which is all a GitHub
      # remote is. A negative class terminated on only three characters, so the
      # strip ran past the repo name and ate whatever followed — fifteen
      # separators defeated it, e.g. `git@github.com:a/b.git;victim@example.org`
      # stripped to nothing and committed clean.
      #
      # The `#<sha>` fragment is deliberately NOT consumed: eating it let
      # `...git#victim@example.org` escape, because `victim` is a legal tag
      # name, and a SHA matches no PII pattern anyway.
      #
      # The left boundary's back-reference closes the prefix attack, so
      # `notgit@github.com:a/b.git` no longer anchors the exemption.
      if sed -E 's#(^|[^A-Za-z0-9._%+-])git\+ssh://git@github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g; s#(^|[^A-Za-z0-9._%+-])git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g' "$file" 2>/dev/null | grep -nE -e "$pattern" >/dev/null; then
        sed -E 's#(^|[^A-Za-z0-9._%+-])git\+ssh://git@github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g; s#(^|[^A-Za-z0-9._%+-])git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g' "$file" 2>/dev/null | grep -nE -e "$pattern"
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
  echo "Use <vault-root> placeholders for paths. Remove personal identifiers."
  echo "See OliverCode/core/contracts/FILE_LOCATION_STANDARD.md"
  echo "=========================================="
  exit 1
fi

echo "  Gate {{N}} passed."
