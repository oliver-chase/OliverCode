"""Tests for check_wording.py (WORDING-1)."""
import tempfile
import unittest
from pathlib import Path

import check_wording as cw


class Wording(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def add(self, rel, text="x\n"):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def messages(self, only=None):
        return [m for _, _, m in cw.scan(self.tmp, only)]

    def test_a_name_ending_in_a_number_is_flagged(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/references/playbook-1.md")
        self.assertEqual(["name ends in a number: playbook-1.md"], self.messages())

    def test_a_dated_name_passes(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/references/2026-10-06-notes.md")
        self.assertEqual([], self.messages())

    def test_a_ticket_reference_in_prose_is_flagged(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/references/x.md", "Moved in issue #279.\n")
        self.assertTrue(self.messages()[0].startswith("ticket reference"))

    def test_a_skill_directly_under_the_root_is_scanned(self):
        self.add("solo/SKILL.md", "Moved in issue #279.\n")
        self.assertEqual(1, len(self.messages()))

    def test_a_ranking_label_and_a_decision_id_pass(self):
        self.add("fam/a/SKILL.md", "Rank them #1 and #2. See `DOC-18`.\n")
        self.assertEqual([], self.messages())

    def test_decisions_and_readme_are_not_scanned(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/DECISIONS.md", "See issue #5.\n")
        self.assertEqual([], self.messages())

    def test_the_staged_list_limits_the_scan(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/references/x.md", "Moved in issue #279.\n")
        self.add("fam/a/references/y.md", "Moved in issue #280.\n")
        got = self.messages([self.tmp / "fam/a/references/y.md"])
        self.assertEqual(1, len(got))

    def test_ablation_without_the_ticket_pattern_nothing_is_caught(self):
        self.add("fam/a/SKILL.md")
        self.add("fam/a/references/x.md", "Moved in issue #279.\n")
        saved = cw.TICKET
        try:
            cw.TICKET = __import__("re").compile(r"never matches here")
            self.assertEqual([], self.messages())
        finally:
            cw.TICKET = saved


if __name__ == "__main__":
    unittest.main()
