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
