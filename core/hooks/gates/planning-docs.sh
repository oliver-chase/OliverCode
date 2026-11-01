PLANNING_CHECKER="$REPO_ROOT/scripts/check-planning-doc-governance.py"
if [[ -f "$PLANNING_CHECKER" ]]; then
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Planning doc governance..."
  if ! python3 "$PLANNING_CHECKER"; then
    echo "  BLOCKED: Planning doc governance failed."
    exit 1
  fi
  echo "  Gate {{N}} passed."
else
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Planning doc governance... skipped (checker not present in this repo)."
fi
