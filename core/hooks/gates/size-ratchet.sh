# SIZE-RATCHET-1. A repo's total line count may fall but never rise past its baseline in
# docs/SIZE-BASELINE.json, so new work cannot quietly rebuild what a cleanup removed. The count
# is skills/audit/scripts/size.sh --total over the staged tree, the same counter `olivercode size`
# uses. A baseline with "lines": null, or no baseline file, skips the gate.
#
# A story that must grow the repo raises "lines" in the same commit, by at most raiseCapPercent
# of the committed baseline (default 2). This gate prints the raise and passes it. A pre-commit
# gate cannot read the commit message, so the commit-msg hook refuses a raise over the cap unless
# the message carries a "Size: L" or "Size: XL" line copied from the story.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Size ratchet..."
SIZE_JSON="$(git show ":docs/SIZE-BASELINE.json" 2>/dev/null || true)"
size_field_of() {
  printf '%s\n' "$2" | sed -n '/"'"$1"'"[[:space:]]*:/{s/.*"'"$1"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p;q;}'
}
size_field() { size_field_of "$1" "$SIZE_JSON"; }
SIZE_BASE="$(size_field lines)"
SIZE_PCT="$(size_field allowancePercent)"
SIZE_COUNTER=""
for candidate in scripts/size.sh skills/audit/scripts/size.sh; do
  if [ -f "$candidate" ]; then SIZE_COUNTER="$candidate"; break; fi
done
if [ -z "$SIZE_JSON" ]; then
  echo "  Gate {{N}} skipped (no docs/SIZE-BASELINE.json; bootstrap adds one)."
elif [ -z "$SIZE_BASE" ]; then
  echo "  Gate {{N}} skipped (docs/SIZE-BASELINE.json has no line count yet; run olivercode size --lower to set it)."
elif [ -z "$SIZE_COUNTER" ]; then
  echo "  BLOCKED: docs/SIZE-BASELINE.json sets a baseline but this repo has no scripts/size.sh to count lines."
  echo "  Run olivercode bootstrap to add it, or remove the baseline file."
  exit 1
else
  SIZE_PCT="${SIZE_PCT:-5}"
  SIZE_TOTAL="$(bash "$SIZE_COUNTER" --total --staged "$REPO_ROOT")"
  SIZE_EXTRA=$(( SIZE_BASE * SIZE_PCT / 100 ))
  if [ -n "$(git diff --cached --name-only -- docs/SIZE-BASELINE.json)" ]; then
    echo "  docs/SIZE-BASELINE.json is part of this commit, so its baseline of $SIZE_BASE lines is trusted."
    SIZE_HEAD_BASE="$(size_field_of lines "$(git show "HEAD:docs/SIZE-BASELINE.json" 2>/dev/null || true)")"
    if [ -n "$SIZE_HEAD_BASE" ] && [ "$SIZE_BASE" -gt "$SIZE_HEAD_BASE" ]; then
      SIZE_CAP_PCT="$(size_field raiseCapPercent)"
      SIZE_CAP=$(( SIZE_HEAD_BASE * ${SIZE_CAP_PCT:-2} / 100 ))
      echo "  This commit raises the baseline by $(( SIZE_BASE - SIZE_HEAD_BASE )) lines (cap $SIZE_CAP without an L or XL story)."
    fi
  fi
  if [ $(( (SIZE_TOTAL - SIZE_BASE) * 100 )) -gt $(( SIZE_BASE * SIZE_PCT )) ]; then
    echo "  BLOCKED: the repo would hold $SIZE_TOTAL lines, over its baseline of $SIZE_BASE by more than the $SIZE_PCT% allowance ($SIZE_EXTRA lines)."
    echo "  The three files that grew most in this commit:"
    git diff --cached --numstat --no-renames --diff-filter=ACM \
      | awk -F'\t' '$1 != "-" && $1 - $2 > 0 { print $1 - $2 "\t" $3 }' | sort -rn | sed -n 1,3p \
      | while IFS="$(printf '\t')" read -r grown path; do echo "    +$grown  $path"; done
    echo "  Remove lines, or raise \"lines\" in docs/SIZE-BASELINE.json in this commit with the story number in the message. A raise over the cap also needs a \"Size: L\" or \"Size: XL\" line."
    exit 1
  fi
  echo "  Gate {{N}} passed ($SIZE_TOTAL lines, baseline $SIZE_BASE)."
fi
