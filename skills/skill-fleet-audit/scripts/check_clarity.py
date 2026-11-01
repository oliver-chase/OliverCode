#!/usr/bin/env python3
"""One-command writing check for every skill under the fleet root: asd-ste100 on each SKILL.md and each
references/*.md beside it, and a description word-count flag.

The frontmatter description is resident in every session, so its length is a real cost. The flag is
advisory. A hard asd-ste100 violation exits 1.

Usage:
    check_clarity.py                 # scan every skill under the fleet root
    check_clarity.py <path-or-dir>   # scan one folder

Tests: python3 -m unittest test_check_clarity   (from this scripts/ folder)
"""

import subprocess
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = FLEET_ROOT = _fleet.FLEET_ROOT
STE_LINT_CANDIDATES = [
    Path.home() / ".claude/skills/asd-ste100/scripts/ste-lint.py",
    Path.home() / ".agents/skills/asd-ste100/scripts/ste-lint.py",
]
DESCRIPTION_WORD_LIMIT = 150
# When this wrapper exists, the lint runs through it: it joins hard-wrapped lines first. The raw linter
# counts sentence length per physical line, so a wrapped paragraph never trips the long-sentence cap.
# Without it, the linter reads the file as written.
STE_JOIN_WRAPPER = FLEET_ROOT / ".githooks" / "ste-lint-joined.py"


def find_ste_lint():
    return next((c for c in STE_LINT_CANDIDATES if c.exists()), None)


def find_skills():
    """(skill_files, lint_files): one SKILL.md per skill for the word count, and each SKILL.md plus its
    references/*.md for the lint. A reference file holds agent-facing instructions like SKILL.md does."""
    skill_files, lint_files = [], []
    for skill_dir in _fleet.find_skills(SKILLS_ROOT):
        skill_files.append(skill_dir / "SKILL.md")
        lint_files.append(skill_dir / "SKILL.md")
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            lint_files.extend(sorted(refs_dir.glob("*.md")))
    return sorted(skill_files), sorted(lint_files)


def main(argv=None):
    global SKILLS_ROOT
    SKILLS_ROOT = _fleet.scan_root(sys.argv[1:] if argv is None else argv, SKILLS_ROOT)
    ste_lint = find_ste_lint()
    skill_files, lint_files = find_skills()
    problems = []
    flags = []

    print(f"Auditing {len(skill_files)} skill(s), {len(lint_files)} file(s) for writing clarity, under {SKILLS_ROOT.name}/\n")

    if ste_lint is None:
        print("asd-ste100 not found on this machine -- skipping lint pass (the word-count check still runs).\n")

    for skill_path in skill_files:
        words = _fleet.description_words(skill_path.read_text(encoding="utf-8"))
        if words > DESCRIPTION_WORD_LIMIT:
            flags.append(f"{skill_path.relative_to(SKILLS_ROOT)}: description is {words} words (over {DESCRIPTION_WORD_LIMIT})")

    if ste_lint:
        for lint_path in lint_files:
            command = ["python3", str(ste_lint), str(lint_path)]
            if STE_JOIN_WRAPPER.is_file():
                command = ["python3", str(STE_JOIN_WRAPPER), str(ste_lint), str(lint_path)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                problems.append(f"{lint_path.relative_to(SKILLS_ROOT)}: asd-ste100 hard violation(s). "
                                f"Run the lint on the file for the lines.")

    if flags:
        print("-- Advisory: description length --")
        for f in flags:
            print(f"  {f}")
        print()

    if problems:
        print(f"-- {len(problems)} problem(s) --")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)

    print("All skills clean: 0 hard asd-ste100 violations.")
    sys.exit(0)


if __name__ == "__main__":
    main()
