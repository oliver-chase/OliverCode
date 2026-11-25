"""The lean engineering skill keeps its defaults explicit and safety-preserving."""

import unittest
from pathlib import Path

from _support import REPO_ROOT


class TestLeanSkill(unittest.TestCase):
    def test_skill_is_indexed_and_has_the_required_workflows(self):
        skill = (REPO_ROOT / "skills" / "lean" / "SKILL.md").read_text(encoding="utf-8")
        index = (REPO_ROOT / "skills" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("`lean`", index)
        for section in ("## Modes", "## Before changing anything", "## Implementation rules",
                        "## Never trade away", "## Keep the interaction human", "## Finish every task",
                        "## Commands", "## Source and attribution"):
            self.assertIn(section, skill)

    def test_shortcuts_do_not_override_safety_or_interactive_first_work(self):
        skill = (REPO_ROOT / "skills" / "lean" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Trust-boundary validation", skill)
        self.assertIn("data loss", skill)
        self.assertIn("Interactive Claude Code conversations are first-class", skill)
        self.assertIn("Never claim a skipped check passed", skill)
        self.assertIn("never fabricate a gain", skill.lower())


if __name__ == "__main__":
    unittest.main()
