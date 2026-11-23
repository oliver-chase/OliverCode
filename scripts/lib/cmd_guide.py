"""`olivercode guide`: a plain-language overview built from the launcher's own command table and the skills' own descriptions, so it cannot drift from either."""

from __future__ import annotations

import re
from pathlib import Path

from lib.cli import COMMANDS

# How work runs, in the order the guide and the README "How work runs" section both print it (#972).
HOW_WORK_RUNS = (
    "You work in one thread, and you say what you want. Each request becomes a story on the repo's board.",
    "`olivercode dispatch N` or `olivercode drain REPO` builds a story in one fresh headless Claude session, in its own worktree. The builder commits and stops, and the runner validates the commit, lands it on main, logs the story and closes it.",
    "`olivercode status` shows what is open.",
)


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
    print("How work runs")
    for sentence in HOW_WORK_RUNS:
        print(f"  {sentence}")
    print("\nFirst steps, in order")
    print("  1. olivercode discover --root <folder holding your repos> --register    add your repos to the fleet")
    print("  2. olivercode health                                                   check this machine")
    print("  3. File your first story: say what you want in Claude Code, and it becomes a story on the board\n")
    print("Commands (olivercode --help prints the same list)")
    for cmd, desc in COMMANDS:
        print(f"  {cmd}\n      {desc}")
    print("\nSkills: say the phrase to Claude Code and the skill loads")
    for name, phrases in skill_triggers(oc_root):
        print(f"  {name}\n      {phrases}")
    print("\nMore: README.md, docs/SETUP.md (setup and commands)")
    return 0
