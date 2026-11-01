"""Fixture tests for check_opening_message.py: a failing fixture per rule and a passing twin.

Run from this scripts/ folder: python3 -m unittest test_check_opening_message
Ablation record: removing the heading test or the list-or-pointer test turns the matching test red.
"""
import tempfile
import unittest
from pathlib import Path

import check_opening_message as com

MESSAGE = "## Opening message\n\n> Intro.\n> 1. One.\n> 2. Two.\n> 3. Three.\n\n## Next\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skill = self.root / "fam" / "alpha"
        self.skill.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def skill_md(self, body):
        (self.skill / "SKILL.md").write_text("---\nname: alpha\n---\n# Alpha\n" + body)

    def test_missing_section_is_a_finding(self):
        self.skill_md("## Step 1\nBody.\n")
        self.assertEqual(1, len(com.find(self.root)))

    def test_section_with_a_list_passes(self):
        self.skill_md(MESSAGE)
        self.assertEqual([], com.find(self.root))

    def test_section_with_too_short_a_list_is_a_finding(self):
        self.skill_md("## Opening message\n\n> 1. One.\n> 2. Two.\n")
        self.assertEqual(1, len(com.find(self.root)))

    def test_pointer_to_an_existing_file_passes(self):
        self.skill_md("## Opening message\n\nSend `references/ask.md` first.\n")
        (self.skill / "references").mkdir()
        (self.skill / "references" / "ask.md").write_text("Ask.\n")
        self.assertEqual([], com.find(self.root))

    def test_pointer_to_a_missing_file_is_a_finding(self):
        self.skill_md("## Opening message\n\nSend `references/ask.md` first.\n")
        self.assertEqual(1, len(com.find(self.root)))

    def test_a_skill_directly_under_the_root_is_checked(self):
        solo = self.root / "solo"
        solo.mkdir()
        (solo / "SKILL.md").write_text("---\nname: solo\n---\n# Solo\n## Step 1\nBody.\n")
        self.skill_md(MESSAGE)
        self.assertEqual(1, len(com.find(self.root)))

    def test_a_commit_checks_only_the_skills_it_touches(self):
        self.skill_md("## Step 1\nBody.\n")
        other = self.root / "fam" / "beta"
        other.mkdir()
        (other / "SKILL.md").write_text("---\nname: beta\n---\n# Beta\n" + MESSAGE)
        self.assertEqual([], com.find(self.root, [str(other / "SKILL.md")]))
        self.assertEqual(1, len(com.find(self.root, [str(self.skill / "SKILL.md")])))


if __name__ == "__main__":
    unittest.main()
