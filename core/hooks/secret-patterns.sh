SECRET_PATTERNS=(
  '[A-Za-z0-9_]{20,}:[A-Za-z0-9_\-]{30,}'   # Colon-separated tokens (bot tokens)
  'sk-[A-Za-z0-9]{20,}'                        # OpenAI/Anthropic-style keys
  'gh[pousr]_[A-Za-z0-9]{36}'                  # GitHub classic, OAuth, user, server and refresh tokens
  'github_pat_[A-Za-z0-9_]{22,}'               # GitHub fine-grained tokens
  'sk-ant-[a-z0-9]+-[A-Za-z0-9_-]{20,}'        # Anthropic keys (hyphens, so the sk- rule above misses them)
  'glpat-[A-Za-z0-9_-]{20,}'                   # GitLab tokens
  'hf_[A-Za-z0-9]{30,}'                        # Hugging Face tokens
  'SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}'   # SendGrid keys
  'whsec_[A-Za-z0-9]{24,}'                     # Webhook signing secrets
  'ya29\.[0-9A-Za-z_-]{20,}'                   # Google OAuth access tokens
  'hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+'  # Slack webhook URLs
  '(AWS|aws)_?(SECRET|secret)_?(ACCESS|access)?_?(KEY|key)?["'\'':= ]+[A-Za-z0-9/+=]{40}'  # AWS secret keys, which carry slashes
  'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+'  # JWT tokens
  '(A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}'   # AWS access key id -- a bare AKIA... has no secret-named var to catch it
  'xox[baprs]-[0-9A-Za-z-]{10,}'               # Slack tokens (hyphens, so the alnum rule below misses them)
  '(sk|rk)_live_[0-9A-Za-z]{20,}'              # Stripe LIVE keys (an underscore, which the sk- shape above misses). test keys deliberately allowed -- they appear in docs
  'AIza[0-9A-Za-z_-]{35}'                      # Google API key
  'npm_[0-9A-Za-z]{36}'                        # npm access token
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'         # Private keys (RSA/EC/DSA/OPENSSH/PKCS8) — matches "BEGIN <TYPE> PRIVATE KEY"
  '(TOKEN|SECRET|KEY|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|AUTH|CREDENTIAL|token|secret|key|password|passwd|api_?key|access_?key|auth|credential|[Pp]assword|[Tt]oken|[Ss]ecret|[Aa]pi[Kk]ey|[Aa]ccess[Kk]ey|[Cc]redential)["'\'':= ]+[A-Za-z0-9]{20,}'  # Secret-named var assigned a 20+ char alphanumeric value (a bare hex-blob pattern false-positives on every git SHA/lockfile hash)
)

# secret_filter PATTERN: reads `grep -n` hits on stdin and prints those that hold a real secret.
# The commit gate and the pre-push scan both call it, so a line one passes the other passes.
# Exempt: the public supabase anon-key meta tag, a line marked "secret-scan: allow", and a hit
# whose every matched value is a placeholder (EXAMPLE, placeholder, your_key, a run of x).
SECRET_ANON_META='<meta name="supabase-anon-key" content="eyJ'
SECRET_PLACEHOLDER='EXAMPLE|[Ee]xample|[Pp]laceholder|PLACEHOLDER|[Yy]our[_-]?([Aa]pi[_-]?)?([Kk]ey|[Tt]oken|[Ss]ecret)|YOUR_|(^|[^A-Za-z0-9])[xX]{8,}([^A-Za-z0-9]|$)'
secret_filter() {
  local pattern="$1" hit
  while IFS= read -r hit; do
    [ -n "$hit" ] || continue
    case "$hit" in *'secret-scan: allow'*|*"$SECRET_ANON_META"*) continue ;; esac
    if printf '%s\n' "$hit" | grep -oE -e "$pattern" | grep -vE -e "$SECRET_PLACEHOLDER" >/dev/null; then
      printf '%s\n' "$hit"
    fi
  done
}
