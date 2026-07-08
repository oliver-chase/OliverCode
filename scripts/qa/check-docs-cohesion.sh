#!/usr/bin/env bash
# ─── QA Docs Cohesion Check ───────────────────────────────────────────────
# Automated documentation audit: broken links, stale references, missing
# docs for existing code. No LLM calls.
#
# Usage: bash scripts/qa/check-docs-cohesion.sh [--verbose]
#
# Exit codes:
#   0 - All checks pass
#   1 - Issues found
#   2 - Critical issues found
#   3 - Script error (unknown option)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERBOSE=false
TARGET_DIR="${REPO_ROOT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=true; shift ;;
    --target) TARGET_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 3 ;;
  esac
done

cd "$TARGET_DIR"

TOTAL_ISSUES=0

echo "=== QA: Documentation Cohesion Check ==="
echo ""

# ─── 1. Find broken markdown links ───────────────────────────────────────
echo "--- 1. Broken Markdown Link Check ---"
# Check for wiki-style links [[...]] that have no matching file
if [ -d "docs" ] || [ -f "README.md" ]; then
  BROKEN=0
  while IFS= read -r md_file; do
    # Find Obsidian-style links [[Target]]
    while IFS= read -r link; do
      target=$(echo "$link" | sed 's/\[\[\(.*\)\]\]/\1/' | sed 's/|.*//' | sed 's/#.*//')
      # Skip external/URL links
      if echo "$target" | grep -q '^http'; then continue; fi
      # Check if the target exists as a .md file somewhere
      # Path-style targets ([[dir/sub/Note|label]]) can never match find -name;
      # resolve them by basename.
      target_base="${target##*/}"
      found=$(find . -name "${target_base}.md" -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | head -1)
      if [ -z "$found" ]; then
        # Check if it's an anchor within the same file
        anchor=$(echo "$link" | sed 's/.*#//' | sed 's/\]\]//')
        if [ -n "$anchor" ] && grep -q "^##.*$anchor" "$md_file" 2>/dev/null; then
          continue
        fi
        echo "  BROKEN LINK in $md_file: $link"
        BROKEN=$((BROKEN + 1))
      fi
    # Strip inline code spans first — e.g. wrangler.toml's `[[crons]]` is TOML
    # array-of-tables syntax, not a wiki link.
    done < <(sed 's/`[^`]*`//g' "$md_file" 2>/dev/null | grep -o '\[\[[^]]*\]\]' || true)
  # runtime/ is gitignored per-machine state (Obsidian vault templates whose
  # wiki-links resolve in the vault, not this repo) and .claude/ is vendored —
  # neither is framework documentation, so neither belongs in this check.
  done < <(find . -name '*.md' -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path './runtime/*' -not -path './.claude/*' -not -path './Prompt Library/*' -not -path './.claude-optimization/*' 2>/dev/null)
  # (Prompt Library notes are vault-authored Obsidian content; their wiki-links
  # resolve against the vault, not this repo.)
  TOTAL_ISSUES=$((TOTAL_ISSUES + BROKEN))
  if [ "$BROKEN" -eq 0 ]; then
    echo "  No broken wiki-links found."
  fi
else
  echo "  No documentation files found."
fi
echo ""

# ─── 2. Check for stale website references ───────────────────────────────
# Repo-opt-in only. OliverCode ships no hardcoded project domains; a repo
# lists its own dead domains (one per line) in .stale-domains at its root
# to opt into this check.
echo "--- 2. Stale Website/Frontend Reference Check ---"
STALE_DOMAINS_FILE="$TARGET_DIR/.stale-domains"
if [ -f "$STALE_DOMAINS_FILE" ]; then
  STALE=""
  while IFS= read -r domain; do
    [ -z "$domain" ] && continue
    hit=$(grep -rnF "$domain" --include='*.md' . 2>/dev/null | grep -v node_modules | grep -v '\.git' | grep -v 'archive/' | grep -v 'CHANGELOG' || true)
    [ -n "$hit" ] && STALE="$STALE
$hit"
  done < "$STALE_DOMAINS_FILE"
  STALE=$(printf '%s\n' "$STALE" | sed '/^$/d' | head -20)
  if [ -n "$STALE" ]; then
    echo "  Possible stale references to frontend/website:"
    echo "$STALE"
    TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
  else
    echo "  No stale website references."
  fi
else
  echo "  No .stale-domains config found in target repo — skipped."
fi
echo ""

# ─── 3. Check for routes without documentation ───────────────────────────
echo "--- 3. Undocumented Route Check ---"
if [ -d "app/api" ]; then
  for route in $(find app/api -name 'route.ts' 2>/dev/null | sort); do
    route_name=$(echo "$route" | sed 's|app/||; s|/route.ts||')
    # Check if any doc mentions this route
    doc_mention=$(grep -rl "$route_name" docs/ README.md 2>/dev/null | head -1 || true)
    if [ -z "$doc_mention" ] && [ "$VERBOSE" = true ]; then
      echo "  UNDOCUMENTED: $route_name"
    fi
  done
fi
echo ""

# ─── 4. Summary stats ────────────────────────────────────────────────────
echo "--- 4. Documentation Stats ---"
MD_COUNT=$(find . -name '*.md' -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | wc -l)
echo "  Total markdown files: $MD_COUNT"
echo ""

echo "=== Summary ==="
echo "Total issues: $TOTAL_ISSUES"
echo ""

if [ "$TOTAL_ISSUES" -gt 0 ]; then
  exit 1
else
  echo "All checks passed."
  exit 0
fi
