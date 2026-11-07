"""`olivercode guide`: a plain-language overview built from the launcher's own command table and skills/INDEX.md, so it cannot drift from either."""

from __future__ import annotations

import re
from pathlib import Path

from lib.cli import COMMANDS

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|([^|]*)\|\s*$")


def skill_triggers(oc_root: Path) -> list[tuple[str, str]]:
    """Each (skill, trigger phrases) row of skills/INDEX.md, in file order."""
    index = oc_root / "skills" / "INDEX.md"
    if not index.is_file():
        return []
    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m and m.group(1) != "Skill":
            rows.append((m.group(1), m.group(3).strip()))
    return rows


def command_guide(oc_root: Path) -> int:
    print("OliverCode gives Claude Code projects one set of rules, skills and Git checks.\n")
    print("First steps")
    print("  1. python3 scripts/olivercode install     link the rules, skills and hooks into ~/.claude")
    print("  2. python3 scripts/olivercode health      check this machine")
    print("  3. python3 scripts/olivercode bootstrap . add the managed files to a project, then run sync-hooks\n")
    print("Commands (olivercode --help prints the same list)")
    for cmd, desc in COMMANDS:
        print(f"  {cmd}\n      {desc}")
    print("\nSkills: say the phrase to Claude Code and the skill loads")
    for name, phrases in skill_triggers(oc_root):
        print(f"  {name}\n      {phrases}")
    print("\nMore: README.md, docs/SETUP.md (setup and commands), skills/INDEX.md (skills)")
    return 0
