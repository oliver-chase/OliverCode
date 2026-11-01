# GATE-LOCAL-1. A repo adds its own blocking checks in .githooks/pre-commit.local. The file is not part
# of this template, so sync-hooks never overwrites it. It gets the staged file list on
# stdin and blocks the commit by exiting non-zero.
if [ -x "$HOOK_DIR/pre-commit.local" ]; then
  echo "[pre-commit] Repo-local gates..."
  printf '%s\n' "$STAGED_FILES" | "$HOOK_DIR/pre-commit.local" || exit 1
fi
