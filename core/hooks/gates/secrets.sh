# Block commits containing API keys, tokens, JWTs, private keys.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Secret scan..."

{{SECRET_PATTERNS}}
for pattern in "${SECRET_PATTERNS[@]}"; do
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      # No path is exempt: a fake key in a test file still reaches the remote. A placeholder is
      # exempt by its value (EXAMPLE, placeholder, your_key, a run of x) or by a line that carries
      # "secret-scan: allow".
      [ "$file" = .gitignore ] && continue
      # Per-line allowlist: ONLY the exact anon-key meta-tag shape is
      # exempt (the anon key is public by design -- it ships in client
      # HTML; service_role is the secret one). Narrow on purpose: a bare
      # "supabase-anon-key" mention elsewhere on a line must NOT bypass
      # the scan (a loose filter had exempted
      # any line containing the literal from every pattern).
      ANON_META='<meta name="supabase-anon-key" content="eyJ'
      # Captured, never piped into `grep -q` or `head`: an early exit there sends SIGPIPE
      # upstream, pipefail turns it into 141, and a large file with a secret passed.
      PLACEHOLDER='EXAMPLE|[Ee]xample|[Pp]laceholder|PLACEHOLDER|[Yy]our[_-]?([Aa]pi[_-]?)?([Kk]ey|[Tt]oken|[Ss]ecret)|YOUR_|x{8,}|X{8,}'
      hits=$(staged_content "$file" 2>/dev/null | grep -nE -e "$pattern" | grep -vF "$ANON_META" \
        | grep -vF 'secret-scan: allow' || true)
      # Keep a line when any matched value is not a placeholder; a word elsewhere on the line never excuses it.
      hits=$(printf '%s\n' "$hits" | while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        if printf '%s\n' "$hit" | grep -oE -e "$pattern" | grep -vE -e "$PLACEHOLDER" >/dev/null; then
          printf '%s\n' "$hit"
        fi
      done || true)
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
