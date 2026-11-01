#!/usr/bin/env python3
"""SKILL-FOLDER-1: a skill's folder holds what travels with it and nothing else.

A skill folder can be zipped or copied by hand. Any developer file in the folder then goes along: a
decision ledger, a cache, a compiled file. A local file such as `.env.local` holds one person's
values and must never ride along.

The decision ledger lives beside the skill folder, in the family folder.

Usage:
    check_skill_folder.py            # report every developer file in a skill folder
    check_skill_folder.py <file> ... # commit gate: fail when a given file sits in a skill folder and is developer material
Exit 1 when any developer file is found.
Tests: python3 -m unittest test_check_skill_folder   (from this scripts/ folder)
"""
import re
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT
DEV_NAMES = {"DECISIONS.md", "conftest.py", ".DS_Store"}
DEV_RE = re.compile(r"^(.*\.local|\.env\.local|.*\.pyc)$")
DEV_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_DIRS = {"node_modules", "vendor", ".git"}


def is_dev(rel):
    """True when a skill-relative path is developer material."""
    parts = Path(rel).parts
    if any(p in DEV_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    return name in DEV_NAMES or bool(DEV_RE.match(name))


def scan(root):
    found = []
    for folder in _fleet.find_skills(root):
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(folder)
            if path.is_file() and not SKIP_DIRS & set(rel.parts) and is_dev(str(rel)):
                found.append(folder.relative_to(root) / rel)
    return found


def gate(root, paths):
    """Commit gate: a staged file inside a skill folder that is developer material."""
    folders = _fleet.find_skills(root)
    bad = []
    for p in paths:
        path = (Path(p) if Path(p).is_absolute() else Path.cwd() / p).resolve()
        if not path.is_file():
            continue  # a deleted file is the move out of the folder; a folder holds no file itself
        for folder in folders:
            try:
                rel = path.relative_to(folder.resolve())
            except ValueError:
                continue
            if not SKIP_DIRS & set(rel.parts) and is_dev(str(rel)):
                bad.append(path.relative_to(root.resolve()))
    return bad


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    files = [a for a in args if not a.startswith("--")]
    if files:
        bad = gate(SKILLS_ROOT, files)
        if not bad:
            return 0
        print(f"{len(bad)} developer file(s) in a skill folder (SKILL-FOLDER-1). Move them to the family folder:")
        for b in bad:
            print(f"  {b}")
        return 1
    found = scan(SKILLS_ROOT)
    for rel in found:
        print(rel)
    print(f"{len(found)} developer file(s) in skill folders")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
