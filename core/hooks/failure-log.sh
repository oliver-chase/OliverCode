
# Failure log: each blocked commit adds one tab-separated line (time, repo, gate, reason) to a local
# file outside every repo, so a failure that recurs can be counted. It writes only on a machine that runs
# the framework, where ~/.olivercode exists, or where OLIVERCODE_FAILURE_LOG names the file, so a clone
# on anyone else's machine writes nothing outside the repo. A gate announces itself through
# GATE_NAME, and the first BLOCKED line any gate prints becomes the reason.
[ -n "${HOOK_DIR:-}" ] || { printf 'failure-log: build this fragment into a hook\n' >&2; exit 1; }
OC_LOG_NAMED="${OLIVERCODE_FAILURE_LOG:+1}"
OLIVERCODE_FAILURE_LOG="${OLIVERCODE_FAILURE_LOG:-${OLIVERCODE_HOME:-$HOME/.olivercode}/failures.log}"
GATE_NAME="hook"
BLOCK_REASON=""
echo() {
  if [ "${1:-}" != "-n" ] && [ -z "$BLOCK_REASON" ] && [[ "$*" == *BLOCKED* ]]; then BLOCK_REASON="$*"; fi
  builtin echo "$@"
}
log_failure() {
  local rc="${1:-0}"
  [ "$rc" -eq 0 ] && return 0
  if [ -n "$OC_LOG_NAMED" ]; then
    mkdir -p "$(dirname "$OLIVERCODE_FAILURE_LOG")" 2>/dev/null || return 0
  elif [ ! -d "$(dirname "$OLIVERCODE_FAILURE_LOG")" ]; then
    return 0
  fi
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "${REPO_ROOT:-$PWD}")" "$GATE_NAME" \
    "$(printf '%s' "${BLOCK_REASON:-exit $rc}" | tr '\t\n' '  ' | sed 's/^ *//' | cut -c1-200)" \
    >> "$OLIVERCODE_FAILURE_LOG" 2>/dev/null || true
}
trap 'log_failure $?' EXIT

