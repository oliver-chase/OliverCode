#!/usr/bin/env python3
"""OUTSIDE-REF-1: a skill's text names nothing outside the skill.

A skill folder is copied to another machine alone. A line that names a vault, a numbered vault
folder, the framework repo, or the history of a name points at a place the new machine does not
have. The scan covers every text file in every skill folder.

Flagged: the word vault, a numbered folder (`04 - Notes ...`), the framework repo name, and
history words (also titled, formerly, renamed from, used to ship, previously-separate).
Any staged file that names the framework repo fails too.
Skipped files: README.md, DECISIONS.md, _REQUIRES, tests, the `_shared/` folder, build output and
this script, whose pattern names what it detects.
The `skill-governance` family writes the rules about vaults and name histories, so it must use those
words. It is checked for the numbered folder and the framework repo name only.

Usage:
    check_outside_refs.py                  # scan every skill
    check_outside_refs.py <file> ...       # scan these files only (the commit gate passes staged files)
Exit 1 when any line is flagged.
Tests: python3 -m unittest test_check_outside_refs   (from this scripts/ folder)
"""
import re
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", "dist", "vendor", "_shared", "tests"}
SKIP_FILES = {"README.md", "DECISIONS.md", "_REQUIRES", "check_outside_refs.py"}
SUFFIXES = {".md", ".py", ".js", ".sh", ".txt", ".example", ".json"}
GOVERNANCE_FAMILY = "skill-governance"
STRICT_PATTERN = re.compile(r"\b0[0-9] - [A-Z]|Oliver[C]ode")
PATTERN = re.compile(
    STRICT_PATTERN.pattern
    + r"|\b[Vv]ault\b|[Aa]lso titled|[Ii]nternally titled|\bformerly\b|renamed from|used to ship"
    r"|previously-separate|used to carry")
NAME_FIELD = re.compile(r"^name: [a-z0-9-]+$")


def scannable(path, base):
    rel = path.relative_to(base)
    name = path.name
    return not set(rel.parts) & SKIP_DIRS and (path.suffix in SUFFIXES or name.endswith(".example")) \
        and name not in SKIP_FILES and not name.startswith("test_") and not name.endswith(".local")


def hits_in(path, pattern=None):
    pattern = pattern or PATTERN
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        # The `name:` field must equal the folder name, so a word in it is not a place the skill names.
        if pattern.search(line) and not NAME_FIELD.match(line):
            out.append((i, line.strip()[:140]))
    return out


def scan(root, only=None):
    only = {Path(p).resolve() for p in only} if only else None
    found = []
    for base in _fleet.find_skills(root):
        for path in sorted(base.rglob("*")):
            if not path.is_file() or not scannable(path, base):
                continue
            if only is not None and path.resolve() not in only:
                continue
            pattern = STRICT_PATTERN if base.resolve().parent.name == GOVERNANCE_FAMILY else PATTERN
            for i, text in hits_in(path, pattern):
                found.append((path.relative_to(root), i, text))
    return found


REPO_WORD = re.compile(r"(?i)oliver-?code")


def repo_word_hits(paths):
    """Any staged text file that names the framework repo."""
    out = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if REPO_WORD.search(line):
                out.append((p, i, line.strip()[:140]))
    return out


def main(argv=None):
    args = [a for a in (sys.argv[1:] if argv is None else argv) if not a.startswith("--")]
    found = scan(SKILLS_ROOT, args or None) + [(Path(p), i, t) for p, i, t in repo_word_hits(args)]
    if not found:
        print("no outside reference in a skill")
        return 0
    print(f"{len(found)} line(s) name a place or a history another machine does not have (OUTSIDE-REF-1):")
    for rel, i, text in found[:60]:
        print(f"  {rel}:{i}: {text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
