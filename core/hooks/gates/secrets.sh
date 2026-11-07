# Block commits containing API keys, tokens, JWTs, private keys.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Secret scan..."

{{SECRET_PATTERNS}}
for pattern in "${SECRET_PATTERNS[@]}"; do
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      # No path is exempt: a fake key in a test file still reaches the remote. secret_filter
      # (secret-patterns.sh) names what a line may carry to pass.
      [ "$file" = .gitignore ] && continue
      # Captured, never piped into `grep -q` or `head`: an early exit there sends SIGPIPE
      # upstream, pipefail turns it into 141, and a large file with a secret passed.
      hits=$(staged_content "$file" 2>/dev/null | grep -nE -e "$pattern" | secret_filter "$pattern" || true)
      if [ -n "$hits" ]; then
        printf '%s\n' "$hits" | sed -n '1,3p'
        echo "  BLOCKED: $file matches secret pattern: $pattern"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    done <<< "$STAGED_FILES"
  fi
done

if [ $VIOLATIONS -gt 0 ]; then
  echo ""
  echo "=========================================="
  echo "COMMIT BLOCKED: $VIOLATIONS potential secret leak(s) found."
  echo "Remove the value from the staged file, or replace it with a placeholder."
  echo "=========================================="
  exit 1
fi

echo "  Gate {{N}} passed."
