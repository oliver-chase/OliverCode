# BACKLOG-HYGIENE-1. The written policy ("finished items are removed rather
# than ticked") held nowhere mechanical, so a fleet repo's backlog reached
# 15,058 lines before anyone noticed.
BACKLOG_GATE="$REPO_ROOT/{{BACKLOG_CHECKER}}"
if [[ -f "$BACKLOG_GATE" ]] && command -v node >/dev/null 2>&1; then
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Backlog hygiene..."
  if ! node "$BACKLOG_GATE" --quiet; then
    node "$BACKLOG_GATE" --quiet
    echo "  BLOCKED: Backlog hygiene failed."
    exit 1
  fi
  echo "  Gate {{N}} passed."
else
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Backlog hygiene... skipped (checker or node not present in this repo)."
fi
