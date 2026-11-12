# Block commits containing API keys, tokens, JWTs, private keys.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Secret scan..."

{{SECRET_PATTERNS}}
# One combined grep per file rules out every file that matches no pattern, and only the rest reach the
# per-pattern loop below. A file matches the union exactly when it matches at least one pattern, so the
# verdict is unchanged. grep -c reads to the end, so a large file never closes the pipe early.
SECRET_CANDIDATES=""
if [ -n "$STAGED_FILES" ]; then
  SECRET_GREP_ARGS=()
  for pattern in "${SECRET_PATTERNS[@]}"; do SECRET_GREP_ARGS+=(-e "$pattern"); done
  while IFS= read -r file; do
    count=$(staged_content "$file" 2>/dev/null | grep -cE "${SECRET_GREP_ARGS[@]}" || true)
    if [ "${count:-0}" -gt 0 ]; then SECRET_CANDIDATES="${SECRET_CANDIDATES}${file}"$'\n'; fi
  done <<< "$STAGED_FILES"
fi
if [ -n "$SECRET_CANDIDATES" ]; then
  secret_tmp=$(mktemp)
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    # No path is exempt: a fake key in a test file still reaches the remote. secret_filter
    # (secret-patterns.sh) names what a line may carry to pass. The staged copy is read once
    # into a file and every pattern scans that file.
    staged_content "$file" > "$secret_tmp" 2>/dev/null
    for pattern in "${SECRET_PATTERNS[@]}"; do
      # Captured, never piped into `grep -q` or `head`: an early exit there sends SIGPIPE
      # upstream, pipefail turns it into 141, and a large file with a secret passed.
      hits=$(grep -nE -e "$pattern" < "$secret_tmp" | secret_filter "$pattern" || true)
      if [ -n "$hits" ]; then
        printf '%s\n' "$hits" | sed -n '1,3p'
        echo "  BLOCKED: $file matches secret pattern: $pattern"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    done
  done <<< "$SECRET_CANDIDATES"
  rm -f "$secret_tmp"
fi

if [ $VIOLATIONS -gt 0 ]; then
  echo ""
  echo "=========================================="
  echo "COMMIT BLOCKED: $VIOLATIONS potential secret leak(s) found."
  echo "Remove the value from the staged file, or replace it with a placeholder."
  echo "=========================================="
  exit 1
fi

echo "  Gate {{N}} passed."
