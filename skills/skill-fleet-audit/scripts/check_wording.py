#!/usr/bin/env python3
"""WORDING-1: shipped files use names a user would say and plain statements.

Two rules over every file in a skill folder (the same scope as OUTSIDE-REF-1):
  name      A file or folder name that ends in a number, such as `playbook-1`. Nobody says it.
  ticket    A ticket reference in prose: "issue #12", "PR #7", "(#123)".
A decision id such as `DOC-18` stays legal in code comments, in skill instructions and in DECISIONS.md.

Usage:
    check_wording.py                 # scan every skill
    check_wording.py <file> ...      # scan these files only (the commit gate passes staged files)
Exit 1 when a name or a ticket reference exists.
Tests: python3 -m unittest test_check_wording   (from this scripts/ folder)
"""
import re
import sys
from pathlib import Path

import _fleet
import check_outside_refs as outside

SKILLS_ROOT = outside.SKILLS_ROOT
NAME = re.compile(r"^[A-Za-z][A-Za-z-]*-\d{1,2}$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TICKET = re.compile(r"\bissue #\d+|\bPR #\d+|\(#\d{2,}\)")
TEXT_SKIP = {"README.md", "DECISIONS.md"}


def name_hits(rel):
    return [part for part in rel.parts if NAME.match(Path(part).stem) and not DATE.search(part)]


def ticket_hits(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [(i, line.strip()[:120]) for i, line in enumerate(text.splitlines(), 1) if TICKET.search(line)]


def scan(root, only=None):
    only = {Path(p).resolve() for p in only} if only else None
    found = []
    for base in _fleet.find_skills(root):
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base)
            if outside.SKIP_DIRS & set(rel.parts):
                continue
            if only is not None and path.resolve() not in only:
                continue
            for part in name_hits(rel):
                found.append((path.relative_to(root), 0, f"name ends in a number: {part}"))
            if not path.is_file() or path.suffix != ".md" or path.name in TEXT_SKIP or path.name.startswith("test_"):
                continue
            for i, line in ticket_hits(path):
                found.append((path.relative_to(root), i, f"ticket reference: {line}"))
    return found


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    paths = [a for a in args if not a.startswith("--")]
    found = scan(SKILLS_ROOT, paths or None)
    if not found:
        print("names and ticket references are clean")
        return 0
    print(f"{len(found)} wording finding(s) (WORDING-1):")
    for rel, i, text in found[:60]:
        print(f"  {rel}{':' + str(i) if i else ''}: {text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
