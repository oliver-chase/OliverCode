# Block commits containing API keys, tokens, JWTs, private keys.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Secret scan..."

SECRET_PATTERNS=(
  '[A-Za-z0-9_]{20,}:[A-Za-z0-9_\-]{30,}'   # Colon-separated tokens (bot tokens)
  'sk-[A-Za-z0-9]{20,}'                        # OpenAI/Anthropic-style keys
  'ghp_[A-Za-z0-9]{36}'                        # GitHub personal access tokens
  'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+'  # JWT tokens
  '(A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}'   # AWS access key id -- a bare AKIA... has no secret-named var to catch it
  'xox[baprs]-[0-9A-Za-z-]{10,}'               # Slack tokens (hyphens, so the alnum rule below misses them)
  '(sk|rk)_live_[0-9A-Za-z]{20,}'              # Stripe LIVE keys (underscore, not the sk- shape above). test keys deliberately allowed -- they appear in docs
  'AIza[0-9A-Za-z_-]{35}'                      # Google API key
  'npm_[0-9A-Za-z]{36}'                        # npm access token
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'         # Private keys (RSA/EC/DSA/OPENSSH/PKCS8) — matches "BEGIN <TYPE> PRIVATE KEY"
  '(TOKEN|SECRET|KEY|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|AUTH|CREDENTIAL|token|secret|key|password|passwd|api_?key|access_?key|auth|credential)["'\'':= ]+[A-Za-z0-9]{20,}'  # Secret-named var assigned a 20+ char alphanumeric value (a bare hex-blob pattern false-positives on every git SHA/lockfile hash)
)

for pattern in "${SECRET_PATTERNS[@]}"; do
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        *.env.example|*mock*|tests/*|*/tests/*|*.test.*|*_test.*|*__tests__*|.gitignore) continue ;;
      esac
      # Per-line allowlist: ONLY the exact anon-key meta-tag shape is
      # exempt (the anon key is public by design -- it ships in client
      # HTML; service_role is the secret one). Narrow on purpose: a bare
      # "supabase-anon-key" mention elsewhere on a line must NOT bypass
      # the scan (a loose filter had exempted
      # any line containing the literal from every pattern).
      ANON_META='<meta name="supabase-anon-key" content="eyJ'
      # Captured, never piped into `grep -q` or `head`: an early exit there sends SIGPIPE
      # upstream, pipefail turns it into 141, and a large file with a secret passed.
      hits=$(grep -nE -e "$pattern" "$file" 2>/dev/null | grep -vF "$ANON_META" || true)
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
  echo "If this is a false positive (test data, example), rename it to match the tests/*.test.* skip patterns above. Otherwise remove the value from the staged file."
  echo "=========================================="
  exit 1
fi

echo "  Gate {{N}} passed."
