#!/usr/bin/env python3
"""OPENING-MSG-1: a skill tells a first-time person what it does and what to send.

A person who triggers a skill with no other words gets the opening message first. It names what the
skill produces, lists what to provide, and says where source material can live. The message sits in
`SKILL.md` under a heading that holds "Opening message" (or "opening message" in a step heading). The
section carries the message itself, as a list of three or more items, or points to a `references/`
file or sibling file that exists.

Usage:
    check_opening_message.py              # scan every skill
    check_opening_message.py PATH...      # scan only the skills that hold these files
Exit 1 when a skill has no opening message section.
Tests: python3 -m unittest test_check_opening_message   (from this scripts/ folder)
"""
import re
import sys
from pathlib import Path

import _fleet

HEADING = re.compile(r"^#{2,3} .*opening message", re.I | re.M)
ITEM = re.compile(r"^\s*(?:>\s*)?(?:\d+\.|-)\s+\S", re.M)
POINTER = re.compile(r"`((?:references|modes)/[^`]+\.md)`")


def section(text):
    """The body of the opening-message section, or None."""
    m = HEADING.search(text)
    if not m:
        return None
    rest = text[m.end():]
    level = len(re.match(r"#+", m.group(0)).group(0))
    nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def find(root, paths=None):
    """`paths` limits the scan to skills that hold one of those files, so a commit checks its own skills."""
    findings = []
    touched = [Path(p).resolve() for p in paths] if paths is not None else None
    for skill in _fleet.find_skills(root):
        if touched is not None and not any(skill.resolve() in t.parents for t in touched):
            continue
        md = skill / "SKILL.md"
        body = section(md.read_text(encoding="utf-8"))
        if body is None:
            findings.append(f"{md}: no 'Opening message' section; a first-time person is not told what to send")
            continue
        has_list = len(ITEM.findall(body)) >= 3
        has_pointer = any((skill / m).is_file() for m in POINTER.findall(body))
        if not (has_list or has_pointer):
            findings.append(f"{md}: the Opening message section holds neither a list of three or more items nor a pointer to an existing file")
    return findings


def main():
    args = sys.argv[1:]
    findings = find(_fleet.FLEET_ROOT, args) if args else find(_fleet.FLEET_ROOT)
    for f in findings:
        print(f)
    if findings:
        sys.exit(1)
    print("opening-message: every skill tells a first-time person what to send. OK.")


if __name__ == "__main__":
    main()
