# managed:validate-queue block, kept in step by sync-hooks and bootstrap
# One per-user queue for validation runs, taken through the validate-queue helper this machine installs.
# Without the helper the run goes ahead unqueued.
VALIDATE_QUEUE_BIN="${VALIDATE_QUEUE_BIN:-$HOME/.local/bin/validate-queue}"
if [[ -z "${VALIDATE_QUEUE_SLOT:-}" ]]; then
  if [[ -x "$VALIDATE_QUEUE_BIN" ]]; then
    VALIDATE_QUEUE_SLOT="$("$VALIDATE_QUEUE_BIN" acquire --pid $$ --label "$(basename "${REPO_ROOT:-$PWD}")" || true)"
    export VALIDATE_QUEUE_SLOT="${VALIDATE_QUEUE_SLOT:-none}"
    # A script's own EXIT trap wins: the queue reaps a slot whose process has exited, so nothing leaks.
    [[ -n "$(trap -p EXIT)" ]] || trap '"$VALIDATE_QUEUE_BIN" release "$VALIDATE_QUEUE_SLOT" >/dev/null 2>&1 || true' EXIT
  else
    echo "validate: no validate-queue helper at $VALIDATE_QUEUE_BIN, running unqueued" >&2
  fi
fi
