#!/bin/bash
# scripts/link-check.sh — Internal reference integrity checker
#
# Two passes over one failure class (a reference naming a path that isn't there): inline markdown links, resolved
# relative to the file that holds them, and backtick-quoted repo paths, resolved from the repo root. Both live in
# scripts/lib/reference_check.py, with the exemptions.
#
# Usage:
#   bash scripts/link-check.sh          # full check
#   bash scripts/link-check.sh --quiet  # summary only
#
# Exit codes: 0 = all internal references valid, 1 = one or more broken references found

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from lib.reference_check import report; sys.exit(report(Path(sys.argv[2]), "--quiet" in sys.argv[3:]))' "$SCRIPT_DIR" "$(cd "$SCRIPT_DIR/.." && pwd)" "$@"
