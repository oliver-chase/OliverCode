#!/usr/bin/env python3
"""Blocking portability gate: a skill folder can be copied to another machine and still work.

One check: `skill-governance/` is the audit tooling and never travels with a skill, so no skill
outside it may cite a path under it with a dependency verb nearby (follows, loads, reads, cites,
per). Machine paths are `check_name_leak.py`'s job.

Scans the `.md`, `.py` and `.json` files of every skill. Never fixes anything.

Usage:
    check_portability.py                 # every skill under the fleet root
    check_portability.py <folder>        # one skill, one family or another fleet root
Exit 1 on any finding.
Tests: python3 -m unittest test_check_portability   (from this scripts/ folder)
"""

import os
import re
import sys
from pathlib import Path

import _fleet

SUFFIXES = (".md", ".py", ".json")
GOVERNANCE_DIR = "skill-governance"
GOVERNANCE_PATH_RE = re.compile(rf"(?<![\w-]){GOVERNANCE_DIR}/[\w.-]+")


def find_skill_files(skill_dir):
    files = []
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        files += [Path(dirpath) / f for f in filenames if f.endswith(SUFFIXES)]
    return files


def check_governance_citation(family_name, rel_path, content):
    """A `skill-governance/` path with a dependency verb in the 60 characters before it."""
    if family_name == GOVERNANCE_DIR:
        return []
    for m in GOVERNANCE_PATH_RE.finditer(content):
        if re.search(r"\b(follow|load|read|cite|per)s?\b", content[max(0, m.start() - 60):m.start()], re.I):
            return [f"{family_name}/{rel_path}: cites a `{GOVERNANCE_DIR}/` path, and `{GOVERNANCE_DIR}` never travels with a skill"]
    return []


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = _fleet.scan_root(argv, _fleet.FLEET_ROOT)
    problems, scanned = [], 0
    for skill in _fleet.find_skills(root):
        family = skill.resolve().parent.name
        for f in find_skill_files(skill):
            scanned += 1
            rel = f.relative_to(skill)
            problems += check_governance_citation(family, rel, f.read_text(encoding="utf-8", errors="ignore"))
    problems = sorted(set(problems))
    print(f"Portability gate: {scanned} file(s) in {len(_fleet.find_skills(root))} skill(s)")
    for p in problems:
        print(f"  {p}")
    if problems:
        print("Copy what the skill needs into its own folder, or drop the citation.")
        return 1
    print("Portability gate clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
