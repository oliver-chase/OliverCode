"""Fixture tests for check_skill_budget.py: a skill over its budget or a row with no skill fails.
A skill within budget or with no row passes, and a test file, a vendored folder or a non-text file adds no words.

Run from this scripts/ folder: python3 -m unittest test_check_skill_budget
"""
import tempfile
import unittest
from pathlib import Path

import check_skill_budget as sb


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "fam/alpha/SKILL.md", "one two three\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_skill_within_budget_passes(self):
        self.assertEqual(sb.find_problems(self.root, {"alpha": 3}), [])

    def test_a_skill_over_budget_fails(self):
        write(self.root, "fam/alpha/references/big.md", "word " * 4000)
        problems = sb.find_problems(self.root, {"alpha": 3})
        self.assertEqual(len(problems), 1)
        self.assertIn("over its budget of 3", problems[0])

    def test_a_skill_with_no_row_is_not_checked(self):
        write(self.root, "fam/beta/SKILL.md", "word " * 4000)
        self.assertEqual(sb.find_problems(self.root, {"alpha": 3}), [])

    def test_a_skill_directly_under_the_root_is_budgeted_too(self):
        write(self.root, "solo/SKILL.md", "word " * 50)
        self.assertEqual(len(sb.find_problems(self.root, {"solo": 3})), 1)

    def test_a_row_for_a_skill_that_is_not_in_the_fleet_fails(self):
        problems = sb.find_problems(self.root, {"alpha": 3, "gone": 50})
        self.assertEqual(len(problems), 1)
        self.assertIn("gone", problems[0])

    def test_tests_vendor_and_binaries_add_no_words(self):
        write(self.root, "fam/alpha/tests/test_x.py", "word " * 500)
        write(self.root, "fam/alpha/test_y.py", "word " * 500)
        write(self.root, "fam/alpha/vendor/lib.js", "word " * 500)
        write(self.root, "fam/alpha/logo.png", "word " * 500)
        self.assertEqual(sb.shipped_words(self.root / "fam/alpha"), 3)


@unittest.skipUnless(sb.BUDGET_FILE.is_file(), "this fleet keeps no audit data here; its own gates read it")
class RealFile(unittest.TestCase):
    def test_every_budget_row_is_a_positive_whole_number(self):
        for name, limit in sb.load_budgets().items():
            self.assertIsInstance(limit, int, name)
            self.assertGreater(limit, 0, name)


if __name__ == "__main__":
    unittest.main()
