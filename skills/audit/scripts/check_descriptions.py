#!/usr/bin/env python3
"""Fails when a skill's description runs over the word cap.

Every skill's frontmatter description loads in every session, so its length is a cost paid all the
time. Writing quality is judged against the voice file, which no script can check.

Usage:
    check_descriptions.py                 # scan every skill under the fleet root
    check_descriptions.py <path-or-dir>   # scan one folder

Tests: python3 -m unittest test_check_descriptions   (from this scripts/ folder)
"""

import sys

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT
DESCRIPTION_WORD_LIMIT = 150


def main(argv=None):
    global SKILLS_ROOT
    SKILLS_ROOT = _fleet.scan_root(sys.argv[1:] if argv is None else argv, SKILLS_ROOT)
    skills = sorted(d / "SKILL.md" for d in _fleet.find_skills(SKILLS_ROOT))
    long = []
    for path in skills:
        words = _fleet.description_words(path.read_text(encoding="utf-8"))
        if words > DESCRIPTION_WORD_LIMIT:
            long.append(f"{path.relative_to(SKILLS_ROOT)}: description is {words} words (cap {DESCRIPTION_WORD_LIMIT})")
    if long:
        print(f"{len(long)} description(s) over the cap, each loaded in every session:")
        for line in long:
            print(f"  {line}")
        sys.exit(1)
    print(f"All {len(skills)} descriptions are within {DESCRIPTION_WORD_LIMIT} words.")
    sys.exit(0)


if __name__ == "__main__":
    main()
