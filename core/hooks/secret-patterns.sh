# The secret patterns both the pre-commit secrets gate and the pre-push scan build in, so the two never drift.
SECRET_PATTERNS=(
  '[A-Za-z0-9_]{20,}:[A-Za-z0-9_\-]{30,}'   # Colon-separated tokens (bot tokens)
  'sk-[A-Za-z0-9]{20,}'                        # OpenAI/Anthropic-style keys
  'gh[pousr]_[A-Za-z0-9]{36}'                  # GitHub classic, OAuth, user, server and refresh tokens
  'github_pat_[A-Za-z0-9_]{22,}'               # GitHub fine-grained tokens
  'sk-(proj|svcacct|admin)-[A-Za-z0-9_-]{20,}'   # OpenAI project, service-account and admin keys (hyphens and underscores, which the sk- rule above misses)
  '[a-z][a-z0-9+.-]*://[^/[:space:]:@]+:[^/[:space:]@]{3,}@[^[:space:]]+'  # A password inside a connection URL, after the user name and before the host
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
  '(TOKEN|SECRET|KEY|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|AUTH|CREDENTIAL|token|secret|key|password|passwd|api_?key|access_?key|auth|credential|[Pp]assword|[Tt]oken|[Ss]ecret|[Aa]pi[Kk]ey|[Aa]ccess[Kk]ey|[Cc]redential)["'\'':= ]+[A-Za-z0-9!@#$%^&*_+/=~-]{20,}'  # Secret-named var assigned a 20+ char value; symbols count, code punctuation such as . ( ) [ ] does not (a bare hex-blob pattern false-positives on every git SHA/lockfile hash)
)

# secret_filter PATTERN: reads `grep -n` hits on stdin and prints those that hold a real secret.
# The commit gate and the pre-push scan both call it, so a line one passes the other passes.
# Exempt: a line marked "secret-scan: allow", and a hit
# whose every matched value is a placeholder (EXAMPLE, placeholder, your_key, a run of x).
SECRET_PLACEHOLDER='EXAMPLE|[Ee]xample|[Pp]laceholder|PLACEHOLDER|[Yy]our[_-]?([Aa]pi[_-]?)?([Kk]ey|[Tt]oken|[Ss]ecret)|YOUR_|(^|[^A-Za-z0-9])[xX]{8,}([^A-Za-z0-9]|$)'
# A generic `key`-style hit whose value is a lowercase hyphenated slug (my-asset-name-5x7) is a name, not a
# credential: real secrets carry mixed case or no hyphens, and every vendor shape above is matched by its own pattern.
secret_not_slug() {
  local m v
  while IFS= read -r m; do
    v=$(printf '%s' "$m" | sed -E "s/^[A-Za-z_]+[\"' :=]+//")
    # A UUID (8-4-4-4-12 hex) and a value after a password name are credentials, never slugs.
    case "$pattern" in '(TOKEN|SECRET'*)
      [[ "$v" =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ ]] || [[ "$m" =~ ^[Pp][Aa][Ss][Ss] ]] ||
        { [[ "$v" =~ ^[a-z0-9]+(-[a-z0-9]+)+$ ]] && continue; } ;; esac
    printf '%s\n' "$m"
  done
}
secret_filter() {
  local pattern="$1" hit
  while IFS= read -r hit; do
    [ -n "$hit" ] || continue
    case "$hit" in *'secret-scan: allow'*) continue ;; esac
    if printf '%s\n' "$hit" | grep -oE -e "$pattern" | grep -vE -e "$SECRET_PLACEHOLDER" | secret_not_slug | grep . >/dev/null; then
      printf '%s\n' "$hit"
    fi
  done
}
