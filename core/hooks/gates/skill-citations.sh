# GATE-SCOPE-1: matched by path shape (`*/SKILL.md`, `*/CLAUDE.md`, `*/references/*.md`),
# never by bare filename, so a reference file gets the same check as a skill file.
#
# GATE-CITATION-1: a staged skill file can cite `#N` as a real GitHub issue
# that was never filed -- two commits did exactly this before anything
# caught it. Checked only when `gh` is installed and already authenticated;
# any network, auth, or rate-limit problem skips the check silently rather
# than blocking a commit on infrastructure the content gate does not own.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Skill citations..."
CITATION_FAILED=0
CITED_NUMS=""
if [ -n "$STAGED_FILES" ]; then
  while IFS= read -r file; do
    case "$file" in
      */SKILL.md|SKILL.md|*/CLAUDE.md|CLAUDE.md|*/references/*.md) ;;
      *) continue ;;
    esac
    hits=$(staged_content "$file" 2>/dev/null | grep -ohE '(^|[^A-Za-z0-9&/#])#0*[1-9][0-9]{0,4}([^A-Za-z0-9_-]|$)' | grep -oE '[0-9]+' | sed 's/^0*//' || true)
    [ -n "$hits" ] && CITED_NUMS="$CITED_NUMS
$hits"
  done <<< "$STAGED_FILES"
fi
CITED_NUMS=$(printf '%s\n' "$CITED_NUMS" | grep -E '^[0-9]+$' | sort -un || true)
if [ -n "$CITED_NUMS" ] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  # Issues and pull requests share one number space, and a skill may cite either.
  ALL_ISSUES=$(cd "$REPO_ROOT" && { gh issue list --state all --limit 5000 --json number --jq '.[].number' && gh pr list --state all --limit 5000 --json number --jq '.[].number'; } 2>/dev/null) || ALL_ISSUES=""
  if [ -n "$ALL_ISSUES" ]; then
    while IFS= read -r n; do
      [ -z "$n" ] && continue
      # A here-string, since grep -q in a pipe ends early and pipefail then reads the writer's SIGPIPE as a miss.
      if ! grep -qx "$n" <<< "$ALL_ISSUES"; then
        echo "  BLOCKED: #$n is cited in a staged skill file but resolves to no real issue."
        CITATION_FAILED=1
      fi
    done <<< "$CITED_NUMS"
  fi
fi

if [ "$CITATION_FAILED" -eq 1 ]; then
  echo "  Fix each citation to a real issue number, or remove it, then re-commit."
  exit 1
fi
echo "  Gate {{N}} passed."
