"""The backlog skill must match RULES: no pull-request wording, no unscheduled sweep, no owner-domain names."""

import re
import unittest

from _support import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "backlog"


class BacklogSkillText(unittest.TestCase):
    def test_skill_matches_rules_and_names_no_repo(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        delegating = (SKILL / "references" / "delegating-a-backlog.md").read_text(encoding="utf-8")
        self.assertNotRegex(skill, r"(?i)pull request")
        self.assertNotRegex(skill, r"(?i)\bweekly\b")
        self.assertNotIn("ask where a config should live", skill)
        self.assertNotIn("Which dimension should I check", skill)
        self.assertNotRegex(delegating, r"(?i)content-flow|ecommerce|pgrep")


if __name__ == "__main__":
    unittest.main()
