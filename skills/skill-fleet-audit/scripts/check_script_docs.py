#!/usr/bin/env python3
"""SCRIPT-DOCS-1: a script's subcommands and the skill's docs name the same set.

A script that builds its commands with `add_parser("name")` has those names listed. Every name must appear in the
skill's `SKILL.md` or `references/` text, and every `scripts/<script> <word>` the text shows must be one of them.
A subcommand nobody documents never gets run. A documented command that does not exist fails the person who tries it.

Usage:
    check_script_docs.py [scan-root]
Exit 1 when any name is undocumented or documented and missing.
Tests: python3 -m unittest test_check_script_docs   (from this scripts/ folder)
"""
import re
import sys

import _fleet

PARSER = re.compile(r"""add_parser\(\s*["']([\w-]+)["']""")


def skill_text(skill):
    parts = [skill / "SKILL.md", *sorted((skill / "references").rglob("*.md")), *sorted((skill / "modes").rglob("*.md"))]
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in parts if p.is_file())


def check(skill):
    problems, text = [], skill_text(skill)
    for script in sorted(p for p in (skill / "scripts").glob("*.py") if not p.name.startswith("test_")):
        names = set(PARSER.findall(script.read_text(encoding="utf-8", errors="ignore")))
        if not names:
            continue
        for name in sorted(names):
            if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
                problems.append(f"{skill.name}: {script.name} has the subcommand `{name}` that no doc names")
        flag = r"--[\w-]+[ \t]+(?:<[^>]+>|\S*[./]\S*)[ \t]+"   # a flag and its path value, as in `--file copy.xlsx`
        shown = set(re.findall(rf"{re.escape(script.name)}[ \t]+(?:{flag})*([a-z][\w-]*)\b", text))
        for word in sorted(shown - names):
            if word in {"to", "and", "or", "for", "from", "with", "on", "in", "is", "the", "then", "that", "when", "it"}:
                continue
            problems.append(f"{skill.name}: the docs show `{script.name} {word}`, which is not a subcommand")
    return problems


def main():
    root = _fleet.scan_root(sys.argv[1:])
    problems = [p for skill in _fleet.find_skills(root) for p in check(skill)]
    for p in problems:
        print(" -", p)
    print(f"{len(problems)} script documentation mismatch(es)" if problems else "Every script subcommand is documented and every documented one exists.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
