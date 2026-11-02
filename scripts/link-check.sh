#!/bin/bash
# scripts/link-check.sh — Internal reference integrity checker
#
# Two passes over the same failure class (a reference naming a path that isn't there):
#   1. Inline markdown links — [text](path.md) — resolved relative to the source file.
#   2. Backtick-quoted repo paths (a token whose first segment is a tracked top-level
#      directory), resolved from the repo root. This is where the references actually
#      are: pass 1 sees ~9 links,
#      pass 2 sees hundreds. Exemptions (downstream-relative contract paths, gitignored
#      local layers, placeholders, template files) live in scripts/lib/reference_check.py.
#
# Usage:
#   bash scripts/link-check.sh          # full check
#   bash scripts/link-check.sh --quiet  # summary only
#
# Exit codes:
#   0 = all internal references valid
#   1 = one or more broken references found

set -euo pipefail

# Script lives at <repo>/scripts/link-check.sh, so the repo root is one level up.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

QUIET=false
for arg in "$@"; do
  [ "$arg" = "--quiet" ] && QUIET=true
done

broken=0
checked=0

$QUIET || echo "=== Internal Link Integrity Check ==="
$QUIET || echo ""

# Scan docs/ plus the other tracked homes of plain [text](path.md) links. Measured
# Scanning only docs/ missed most real occurrences — scanning only
# docs/ made the checker a near no-op. (Exclude docs/archive/ — archived links may break.)
SCAN_ROOTS=("$REPO_ROOT/docs" "$REPO_ROOT/core" "$REPO_ROOT/shared" "$REPO_ROOT/skills"
  "$REPO_ROOT/README.md" "$REPO_ROOT/CLAUDE.md")
while IFS= read -r -d '' file; do
  rel_path="${file#$REPO_ROOT/}"
  dir="$(dirname "$file")"
  
  # Extract markdown links: [text](path/to/file.md)
  # Only match links ending in .md (internal refs), excluding external URLs
  while IFS= read -r link; do
    # Skip external URLs
    [[ "$link" =~ ^https?:// ]] && continue
    [[ "$link" =~ ^# ]] && continue  # anchor-only links are fine
    
    # Resolve + normalize relative to the source file's dir. python normpath works even
    # when an intermediate dir is missing — the old `cd`-based normalize silently emptied
    # `target` for those, hiding genuinely broken links as "valid".
    target="$(python3 -c "import os,sys; print(os.path.normpath(sys.argv[1]))" "$dir/$link")"

    # runtime/control-plane/ is gitignored, local-only state (docs/RULES.md) —
    # links into it (e.g. README.md -> runtime/control-plane/README.md) are valid
    # documentation of an optional local layer, not broken references. A fresh/
    # standalone clone genuinely won't have this directory (G4 stranger-clone test).
    case "$target" in
      "$REPO_ROOT/runtime/control-plane/"*) checked=$((checked + 1)); continue ;;
    esac

    if [ ! -f "$target" ]; then
      echo "  [BROKEN] $rel_path → $link (resolved to $target, not found)"
      broken=$((broken + 1))
    fi
    checked=$((checked + 1))
  # Extract [text](path.md) links portably. BSD grep has no -P, and `grep -oP`
  # fails silently on stock macOS grep — use -oE plus sed, never -P.
  done < <(grep -oE '\]\([^)]*\.md\)' "$file" 2>/dev/null | sed -E 's/^\]\(//; s/\)$//' || true)
done < <(find "${SCAN_ROOTS[@]}" -name "*.md" -not -path "*/archive/*" -print0)

# ─── Pass 2: backtick-quoted repo paths ──────────────────────────────────────
ref_out="$(python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.reference_check import check_references
checked, failures = check_references(Path(sys.argv[2]))
print(checked)
for f in failures:
    print(f)
' "$SCRIPT_DIR" "$REPO_ROOT")"
ref_checked="$(printf '%s\n' "$ref_out" | head -1)"
ref_failures="$(printf '%s\n' "$ref_out" | tail -n +2)"
ref_broken=0
if [ -n "$ref_failures" ]; then
  printf '%s\n' "$ref_failures"
  ref_broken=$(printf '%s\n' "$ref_failures" | grep -c 'BROKEN REF' || true)
fi
broken=$((broken + ref_broken))

$QUIET || echo ""
$QUIET || echo "--- Summary ---"
$QUIET || echo "  Markdown links checked:   $checked"
$QUIET || echo "  Backtick refs checked:    $ref_checked"
$QUIET || echo "  Broken: $broken"

if [ "$broken" -gt 0 ]; then
  echo ""
  echo "FAIL: $broken broken internal reference(s) found"
  exit 1
fi

$QUIET || echo ""
$QUIET || echo "OK: all internal references valid"
exit 0
