# DUPLICATION-HOOK-1. A passage of 15 words or more may live in one markdown file only, so a rule
# keeps one home across docs, skills, references and templates. The shared check
# (scripts/duplication_check.py, shipped to adopted repos by bootstrap; OliverCode keeps it at #OC-ONLY
# scripts/lib/duplication_check.py) reads every tracked markdown file and reports each passage that #OC-ONLY
# (scripts/duplication_check.py) reads every tracked markdown file and reports each passage that #PROJECT-ONLY
# a staged file shares with another file, naming both. Files outside the commit are judged as they
# stand, so an old duplicate between two untouched files blocks nothing here; validate.sh reports it.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Duplicate text..."
DUP_CHECKER=""
for candidate in scripts/duplication_check.py scripts/lib/duplication_check.py; do
  if [ -f "$candidate" ]; then DUP_CHECKER="$candidate"; break; fi
done
DUP_FILES=()
while IFS= read -r dup_file; do
  case "$dup_file" in *.md) DUP_FILES+=("$dup_file") ;; esac
done <<< "$STAGED_FILES"
if [ ${#DUP_FILES[@]} -eq 0 ]; then
  echo "  Gate {{N}} passed (no staged markdown)."
elif [ -z "$DUP_CHECKER" ]; then
  echo "  Gate {{N}} skipped (no scripts/duplication_check.py; run olivercode bootstrap to add it)."
elif ! command -v python3 >/dev/null 2>&1; then
  echo "  Gate {{N}} skipped (python3 is not installed)."
else
  DUP_OUT="$(python3 "$DUP_CHECKER" --root "$REPO_ROOT" --staged-only "${DUP_FILES[@]}" 2>&1)" && DUP_RC=0 || DUP_RC=$?
  if [ "$DUP_RC" -ne 0 ]; then
    printf '%s\n' "$DUP_OUT" | sed 's/^/  /'
    echo "  BLOCKED: a staged markdown file repeats a passage that another file already holds."
    echo "  Keep the rule in one file and point the other at it, or declare a deliberate reuse in DECLARED_MARKERS with a reason."
    exit 1
  fi
  echo "  Gate {{N}} passed (${#DUP_FILES[@]} staged markdown file(s) checked)."
fi
