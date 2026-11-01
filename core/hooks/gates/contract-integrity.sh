# Two checks: no hardcoded container paths in staged code, and every path the
# control plane declares as a dependency still exists. OliverCode-only -- the
# downstream template ships neither.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Contract integrity..."

# `/workspace/` is the container-path class this framework bans; every path must
# derive from the script's own location. (A `_Management/` pattern sat here too,
# guarding a vault directory that has left zero trace in any of the six repos or
# in git history -- removed rather than kept scanning for something extinct.)
# tests/* is skipped for the same reason Gates 1 and 3 skip it: a test proving this
# gate blocks a forbidden path must contain that path as a fixture.
if [ -n "$STAGED_FILES" ]; then
  while IFS= read -r file; do
    case "$file" in
      *.md|*.txt|docs/*|tests/*|*/tests/*|*.test.*|*_test.*|.githooks/pre-commit|core/hooks/*|scripts/check-planning-doc-governance.py) continue ;;
    esac
    if grep -q '/workspace/' "$file" 2>/dev/null; then
      echo "  BLOCKED: $file contains hardcoded /workspace/ path reference"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  done <<< "$STAGED_FILES"
fi

# Verify OLIVERCODE_DEPENDENCY.md declared paths still exist
DEP_DOC="$REPO_ROOT/runtime/control-plane/OLIVERCODE_DEPENDENCY.md"
if [ -f "$DEP_DOC" ]; then
  # Declared paths are backtick-quoted and repo-relative (e.g. `shared/repo-profiles.json`,
  # `core/contracts/`). Resolve the OliverCode-relative ones under $REPO_ROOT; skip paths
  # outside this repo. (chr(96) avoids embedding a literal backtick in this shell string.)
  DEP_PATHS=$(python3 -c "
import re
bt = chr(96)
content = open('$DEP_DOC').read()
oc_dirs = ('shared/', 'core/', 'docs/', 'scripts/', 'tooling/', 'runtime/', '.githooks/')
for m in re.findall(bt + '([^' + bt + ']+)' + bt, content):
    if m.startswith(oc_dirs):
        print(m)
" 2>/dev/null || echo "")
  for dep_path in $DEP_PATHS; do
    if [ ! -e "$REPO_ROOT/$dep_path" ]; then
      echo "  BLOCKED: OLIVERCODE_DEPENDENCY.md declares '$dep_path' but it does not exist on disk"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  done
fi

if [ $VIOLATIONS -gt 0 ]; then
  echo ""
  echo "=========================================="
  echo "COMMIT BLOCKED: $VIOLATIONS contract integrity violation(s)."
  echo "Fix skill references or replace hardcoded paths before committing."
  echo "=========================================="
  exit 1
fi

echo "  [OK] Contract integrity"
