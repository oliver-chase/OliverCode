# HTTPS alone isn't the risk -- a `gh auth login` credential can carry `workflow`
# scope over HTTPS just fine. The real risk is legacy git credential caching
# (a bare PAT/password with no workflow scope) or an SSH key with no workflow
# grant. Check the actual credential's scopes via `gh api`, don't assume from
# the remote URL scheme.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Workflow push auth..."
WORKFLOW_STAGED=$(printf '%s\n' "$STAGED_FILES" | grep -E '^\.github/workflows/.*\.ya?ml$' || true)
if [[ -n "$WORKFLOW_STAGED" ]]; then
  HAS_WORKFLOW_SCOPE=false
  if command -v gh &>/dev/null && gh auth status &>/dev/null; then
    SCOPES=$(gh api user -i 2>/dev/null | grep -i "^x-oauth-scopes:" || true)
    if echo "$SCOPES" | grep -qiw "workflow"; then
      HAS_WORKFLOW_SCOPE=true
    fi
  fi
  if [[ "$HAS_WORKFLOW_SCOPE" == false ]]; then
    # Advisory: an SSH key or a fine-grained token can push workflows with no scope header to read.
    echo "  WARNING: workflow file(s) staged and no workflow-scoped gh credential found."
    echo "  GitHub rejects the push without workflow scope: gh auth refresh -s workflow"
    echo "$WORKFLOW_STAGED" | sed 's/^/    /'
  else
    echo "  [OK] gh credential has workflow scope."
  fi
fi

echo "  Gate {{N}} passed."
