#!/usr/bin/env python3
"""RETIRED-TERMS-1: fails when governance docs, a SKILL.md or a README.md still teach a term that a
decision retired.

A doc can describe a model the fleet already dropped, and no other check sees it. The list of
retired terms lives in the fleet's `.fleet-audit/retired-terms.json`, each with the decision that retired it
and the text to use instead. This check scans:
  - every `SKILL.md` and every `README.md` in the fleet
  - every `.md` file under `skill-governance/`
It skips `DECISIONS.md` (a decision names the term it retires), the list itself, test folders and
generated folders. A line that must quote a retired term ends with `<!-- allow-retired -->`.

It also reads every `DECISIONS.md` row that says "Reversed by `ID`". The reversing decision must own a
row in the list, so a reversal cannot land without the wording it retires. A reversal that retires no
wording ends its row with the same allow marker.

Usage:
    check_retired_terms.py [ROOT]    # scan the fleet, or one folder
Exit 1 when any line holds a retired term.
Tests: python3 -m unittest test_check_retired_terms   (from this scripts/ folder)
"""

import json
import re
import sys
from pathlib import Path

from _fleet import FLEET_ROOT, fleet_data, read_fleet_data, scan_root

LIST_FILE = fleet_data("retired-terms.json")
SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "worktrees", "tests", ".claude"}
SKIP_NAMES = {"DECISIONS.md"}
ALLOW_MARKER = "allow-retired"
REVERSED_BY = re.compile(r"Reversed by `([A-Z0-9-]+)`")


def load_terms(path=LIST_FILE):
    entries = json.loads(read_fleet_data(path))["terms"]
    return [(e["id"], re.compile(e["pattern"], re.IGNORECASE), e["decision"], e["use"]) for e in entries]


def scanned_files(root):
    for path in sorted(Path(root).rglob("*.md")):
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS or path.name in SKIP_NAMES or path.name.startswith("test_"):
            continue
        yield path


def find_retired(root, terms):
    found = []
    for path in scanned_files(root):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for term_id, rx, decision, use in terms:
                if rx.search(line):
                    found.append((path, number, term_id, decision, use))
    return found


def find_unmatched_reversals(root, terms):
    """(path, line, reversing decision) for each reversal whose decision owns no row in `terms`."""
    owned = {decision for _id, _rx, decision, _use in terms}
    found = []
    for path in sorted(Path(root).rglob("DECISIONS.md")):
        if set(path.relative_to(root).parts) & SKIP_DIRS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            match = REVERSED_BY.search(line)
            if match and ALLOW_MARKER not in line and match.group(1) not in owned:
                found.append((path, number, match.group(1)))
    return found


def main():
    root = scan_root(sys.argv[1:])
    terms = load_terms(LIST_FILE)
    found = find_retired(root, terms)
    unmatched = find_unmatched_reversals(root, terms)
    for path, number, decision in unmatched:
        print(f"{path.relative_to(root)}:{number} -- reversed by '{decision}', which owns no row in the fleet's .fleet-audit/retired-terms.json. Add the wording it retires, or end the row with <!-- allow-retired -->.")
    for path, number, term_id, decision, use in found:
        print(f"{path.relative_to(root)}:{number} -- retired term '{term_id}' ({decision}). {use}")
    if found or unmatched:
        print(f"\n{len(found)} retired term(s) still taught, {len(unmatched)} reversal(s) with no retired-terms row.")
        return 1
    print("Retired-terms check clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
