"""Intake check (#728) and the one first-run owner-queue line (#729)."""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner, intake  # noqa: E402

GOOD = """**As the owner**, I want a thing, so that it works.

```gherkin
Feature: A thing
  Scenario: Main
    Given a
    When b
    Then c
```

Epic: #1
Priority: P2. Size: S. Work type: Story.
"""


class TestIntake(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        p.start()
        self.addCleanup(p.stop)
        self.filed = []

    def run_check(self, issues):
        return intake.check("Alpha", "o/r", 1, fetch=lambda slug: issues, file=lambda *a: self.filed.append(a))

    def test_ten_template_less_issues_fail_and_file_one_story(self):
        issues = [{"number": n, "title": f"t{n}", "body": "just a line"} for n in range(1, 11)] + [{"number": 11, "title": "ok", "body": GOOD}]
        bad, line = self.run_check(issues)
        self.assertTrue(bad)
        self.assertIn("10 open issue(s) lack the story template", line)
        self.assertEqual(1, len(self.filed))
        self.assertEqual("Rewrite 10 issues to the story template", self.filed[0][1])
        import check_story_format
        self.assertEqual([], check_story_format.check_body(self.filed[0][2]))

    def test_an_open_rewrite_story_files_no_second_one_and_a_few_issues_pass(self):
        issues = [{"number": n, "title": f"t{n}", "body": "x"} for n in range(1, 8)]
        issues.append({"number": 9, "title": "Rewrite 7 issues to the story template", "body": GOOD})
        bad, line = self.run_check(issues)
        self.assertTrue(bad)
        self.assertEqual([], self.filed)
        bad, _ = self.run_check([{"number": 1, "title": "t", "body": "x"}, {"number": 2, "title": "ok", "body": GOOD}])
        self.assertFalse(bad)

    def test_an_unreadable_repo_is_never_reported_clean(self):
        def boom(slug):
            raise RuntimeError("rate limited")
        bad, line = intake.check("Alpha", "o/r", fetch=boom)
        self.assertTrue(bad)
        self.assertIn("did not run", line)

    def test_plan_starts_the_story_that_unblocks_more_first(self):
        def story(n, blocking=0):
            return {"number": n, "title": "t", "body": "Priority: P1.\nFiles area: a.py", "labels": [],
                    "issue_dependencies_summary": {"total_blocking": blocking}}
        self.assertEqual([[2, 1]], intake.plan([story(1), story(2, 2)])["groups"])


class TestPrevention(unittest.TestCase):
    """Repeated blockers: 3 entries file one story, an open story gets a comment, 2 entries file nothing."""

    def setUp(self):
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_FAILURE_LOG": str(home / "failures.log")})
        p.start()
        self.addCleanup(p.stop)
        self.filed, self.comments = [], []

    def sweep(self, issues):
        return intake.prevention("o/r", 7, fetch=lambda slug: issues, file=lambda *a: self.filed.append(a),
                                 comment=lambda *a: self.comments.append(a))

    def test_three_entries_file_one_story_and_two_file_nothing(self):
        from lib import failure_log
        for _ in range(2):
            failure_log.record("gate 4", "land interrupted", "r")
        self.assertEqual([], self.sweep([]))
        self.assertEqual([], self.filed)
        failure_log.record("gate 4", "land interrupted", "r")
        self.assertEqual(1, len(self.sweep([])))
        self.assertEqual(1, len(self.filed))
        self.assertIn("gate 4: land interrupted", self.filed[0][1])
        self.assertIn("Occurrences:", self.filed[0][2])
        import check_story_format
        self.assertEqual([], check_story_format.check_body(self.filed[0][2]))

    def test_an_open_story_gets_a_comment_and_no_second_story(self):
        from lib import failure_log
        for _ in range(3):
            failure_log.record("gate 4", "land interrupted", "r")
        issues = [{"number": 42, "title": intake.PREVENT + "gate 4: land interrupted", "body": GOOD}]
        self.sweep(issues)
        self.assertEqual([], self.filed)
        self.assertEqual(1, len(self.comments))
        self.assertEqual(42, self.comments[0][1])
        failure_log.record("gate 4", "land interrupted", "r")
        self.sweep(issues)
        self.assertEqual(2, len(self.comments))
        self.sweep(issues)
        self.assertEqual(2, len(self.comments))


class TestTurnBudget(unittest.TestCase):
    def test_turn_budget_scales_with_story_size_without_restarting_context_too_early(self):
        self.assertEqual((40, 40, 60, 60), tuple(intake.turns(size) for size in ("XS", "S", "M", "L")))


if __name__ == "__main__":
    unittest.main()
