"""`olivercode guide`: a plain-language overview built from the launcher's own command table and the skills' own descriptions, so it cannot drift from either."""

from __future__ import annotations

import re
from pathlib import Path

from lib.cli import COMMANDS

def skill_triggers(oc_root: Path) -> list[tuple[str, str]]:
    """Each (skill, what it does and the phrases that load it) pair from the skills' own descriptions, sorted by name."""
    rows = []
    for md in sorted((oc_root / "skills").glob("*/SKILL.md")):
        m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|^---)", md.read_text(encoding="utf-8"), re.S | re.M)
        if m:
            text = " ".join(m.group(1).strip().lstrip(">|-").strip().strip("\"'").split())
            sentences = [s.strip().rstrip(".") + "." for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
            trigger = next((s for s in sentences[1:] if s.lower().startswith(("trigger", "use when", "use it when"))), "")
            rows.append((md.parent.name, " ".join(filter(None, (sentences[0] if sentences else "", trigger)))))
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
    print("\nMore: README.md, docs/SETUP.md (setup and commands), docs/CATALOG.md (every part)")
    return 0
