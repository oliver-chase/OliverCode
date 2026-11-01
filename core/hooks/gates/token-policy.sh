# Was manual-only (scripts/validate.sh --check-token-policy) -- moved into the
# real hook so it can't be skipped by forgetting to run validate.sh before commit.
GATEKEEPER="$REPO_ROOT/scripts/orchestration-gatekeeper.py"
if [[ -f "$GATEKEEPER" ]]; then
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Token policy..."
  if ! python3 "$GATEKEEPER" --check-token-policy; then
    echo "  BLOCKED: Token policy check failed."
    exit 1
  fi
  echo "  Gate {{N}} passed."
else
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Token policy... skipped (gatekeeper not present in this repo)."
fi
