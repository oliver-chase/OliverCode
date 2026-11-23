# Block commits containing personal identifiers: home folder paths and email addresses.
# A repo whose own files must hold a pattern, such as a gate that names the patterns it blocks, lists
# those files under "exempt" in docs/PII-GATE.json, each with a line in "reasons".
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: PII scan..."
PII_EXEMPT="$(gate_list docs/PII-GATE.json exempt)"

# A test or mock file is scanned like any other, except that obvious placeholders may stay: example addresses,
# the SSH form of a GitHub remote and a handful of fake home folders. A real path or address in a fixture blocks.
strip_fixture_placeholders() {
  case "$1" in
    tests/*|*/tests/*|*.test.*|*_test.*|*__tests__*|*/mocks/*|*.mock.*|*_mock.*)
      sed -E 's#[A-Za-z0-9._%+-]+@(example\.(com|org|net|invalid|test)|anthropic\.com)#X#g; s#git@github\.com#X#g; s#/(Users|home)/(example|someone|me|x)([/"'"'"' ]|$)#X\3#g' ;;
    *) cat ;;
  esac
}

PII_PATTERNS=(
  '(^|[^[:alnum:]._/-])/Users/[A-Za-z0-9._-]+([/"'\'' ]|$)'                   # macOS home directory paths, with or without a trailing slash
  '(^|[^[:alnum:]._/-])/home/[A-Za-z0-9._-]+([/"'\'' ]|$)'                    # Linux home directory paths
  '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # Email addresses (any domain)
)

for pattern in "${PII_PATTERNS[@]}"; do
  if [ -n "$TEXT_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        *.env.example|.gitignore|docs/PII-GATE.json|.githooks/*) continue ;;
      esac
      matches_glob "$file" "$PII_EXEMPT" && continue
      # Strip known non-PII strings before matching. `git@github.com` is the SSH form npm
      # writes into package-lock.json for a git dependency, a protocol user on a public host,
      # so a lockfile with a git dependency stays committable.
      #
      # The strip works on the match, so anything else on the same line is still scanned.
      # Its class is positive and bounded to owner/repo, which is all a GitHub remote is,
      # so a separator after the repo name ends the strip. The `#<sha>` fragment is left in
      # place, since a tag name after it could hide an address. The left boundary stops a
      # longer word such as `notgit@github.com` from anchoring the exemption.
      if hits=$(staged_content "$file" 2>/dev/null | sed -E 's#(^|[^A-Za-z0-9._%+-])git\+ssh://git@github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g; s#(^|[^A-Za-z0-9._%+-])git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\1#g' | strip_fixture_placeholders "$file" | grep -nE -e "$pattern"); then
        echo "$hits"
        echo "  BLOCKED: $file contains PII matching pattern: $pattern"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    done <<< "$TEXT_FILES"
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
