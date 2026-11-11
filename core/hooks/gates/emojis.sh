# Block ALL emojis and Unicode icons. Plain text only. No exceptions.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Icon/Emoji scan..."

EMOJI_PATTERN='[\x{1F600}-\x{1F64F}\x{1F300}-\x{1F5FF}\x{1F680}-\x{1F6FF}\x{1F1E0}-\x{1F1FF}\x{2600}-\x{26FF}\x{2700}-\x{27BF}\x{FE00}-\x{FE0F}\x{1F900}-\x{1F9FF}\x{1FA00}-\x{1FA6F}\x{1FA70}-\x{1FAFF}\x{2300}-\x{23FF}\x{2B50}\x{2764}\x{1F004}\x{1F0CF}\x{2934}-\x{2935}\x{25AA}-\x{25FE}\x{2B05}-\x{2B07}\x{2B1B}-\x{2B1C}\x{3030}\x{303D}\x{3297}\x{3299}\x{2139}\x{2328}\x{23CF}\x{24C2}\x{25B6}\x{23E9}-\x{23F3}\x{23F8}-\x{23FA}\x{200D}\x{20E3}]'

# perl backs this gate. Without it the scan below silently finds nothing and the gate
# "passes" -- a fail-OPEN on the one rule this framework calls universal. Assert it.
if ! command -v perl >/dev/null 2>&1; then
  echo "  BLOCKED: perl not found, and Gate {{N}} (emoji scan) cannot run without it."
  echo "  Install perl, or this gate would silently pass every commit."
  exit 1
fi

# BSD grep has no -P, and `grep -nP` fails silently inside an if-condition, so this
# gate must never use it. perl handles the \x{...} ranges natively.
if [ -n "$STAGED_FILES" ]; then
  while IFS= read -r file; do
    # Instagram captions are posted copy, and emojis belong in them. The ledgers under data/ hold those captions.
    case "$file" in data/*.csv|data/*.json|data/*.jsonl) continue ;; esac
    EMOJI_HITS=$(staged_content "$file" 2>/dev/null | perl -CSD -ne 'print "$.: $_" if /'"$EMOJI_PATTERN"'/' || true)
    if [ -n "$EMOJI_HITS" ]; then
      echo "$EMOJI_HITS"
      echo "  BLOCKED: $file contains emojis or icons."
      echo "  Zero emojis allowed — plain text only."
      exit 1
    fi
  done <<< "$STAGED_FILES"
fi

echo "  Gate {{N}} passed."
