"""Intake check (#728) and the repeated-blocker report. Neither files a story (#1275)."""

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

    def run_check(self, issues):
        return intake.check("Alpha", "o/r", fetch=lambda slug: issues)

    def test_ten_template_less_issues_fail_and_are_named_and_no_story_is_filed(self):
        issues = [{"number": n, "title": f"t{n}", "body": "just a line"} for n in range(1, 11)] + [{"number": 11, "title": "ok", "body": GOOD}]
        bad, line = self.run_check(issues)
        self.assertTrue(bad)
        self.assertIn("10 open issue(s) lack the story template", line)
        self.assertIn("#1, #2", line)
        self.assertFalse(hasattr(intake, "candidate"))
        self.assertFalse(hasattr(intake, "BODY"))

    def test_a_few_issues_without_the_template_pass(self):
        bad, _ = self.run_check([{"number": 1, "title": "t", "body": "x"}, {"number": 2, "title": "ok", "body": GOOD}])
        self.assertFalse(bad)

    def test_an_unreadable_repo_is_never_reported_clean(self):
        def boom(slug):
            raise RuntimeError("rate limited")
        bad, line = intake.check("Alpha", "o/r", fetch=boom)
        self.assertTrue(bad)
        self.assertIn("did not run", line)


class TestRepeatedBlockers(unittest.TestCase):
    """A blocker the failure log holds three times is reported, two are not, and nothing is filed, commented or remembered (#1275)."""

    def setUp(self):
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_FAILURE_LOG": str(home / "failures.log")})
        p.start()
        self.addCleanup(p.stop)
        self.home = home

    def test_three_entries_are_reported_and_two_are_not(self):
        from lib import failure_log
        for _ in range(2):
            failure_log.record("gate 4", "land interrupted", "r")
        self.assertEqual([], intake.repeated_blockers())
        failure_log.record("gate 4", "land interrupted", "r")
        with mock.patch("subprocess.run") as gh:
            lines = intake.repeated_blockers()
        self.assertEqual(1, len(lines))
        self.assertIn("gate 4: land interrupted blocked 3 times", lines[0])
        gh.assert_not_called()
        self.assertFalse((self.home / "blocker-seen.json").exists())

    def test_a_refusal_from_a_guard_the_tree_no_longer_has_is_not_reported(self):
        self.assertEqual([], intake.repeated_blockers({("gone_guard", "x"): ["t1", "t2", "t3"]}))


if __name__ == "__main__":
    unittest.main()
