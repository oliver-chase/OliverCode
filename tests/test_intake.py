"""Size and Priority, the filing fit check and the repeated-blocker report. None files a story (#1275)."""

import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import intake  # noqa: E402


class TestSizeAndPriority(unittest.TestCase):
    def test_the_stated_lines_win_and_the_body_length_sizes_the_rest(self):
        self.assertEqual("S", intake.size_of({"body": "Priority: P1. Size: S. Work type: Story."}))
        self.assertEqual("P1", intake.priority_of({"body": "Priority: P1. Size: S."}))
        self.assertEqual("XS", intake.size_of({"body": "short"}))
        self.assertEqual("XL", intake.size_of({"body": "x" * 5000}))
        self.assertEqual("P0", intake.priority_of({"title": "A leaked secret", "body": ""}))
        self.assertEqual("P1", intake.priority_of({"title": "The run is broken", "body": ""}))
        self.assertEqual("P2", intake.priority_of({"title": "Add a flag", "body": ""}))


class TestFit(unittest.TestCase):
    def test_an_overlapping_open_story_gets_one_related_line_and_a_repeat_keeps_one(self):
        stories = {7: {"body": "Files area: scripts/lib/intake.py"}}
        with mock.patch.object(intake, "tracked", return_value={"scripts", "scripts/lib", "scripts/lib/intake.py"}):
            once, _ = intake.fit("Files area: scripts/lib/intake.py\n", "New", stories, ".")
            twice, _ = intake.fit(once, "New", stories, ".")
        self.assertEqual("Related: #7 (Files area overlaps)", once.splitlines()[-1])
        self.assertEqual(once, twice)

    def test_a_path_not_on_main_and_not_created_is_printed(self):
        with mock.patch.object(intake, "tracked", return_value={"a.py"}):
            _, lines = intake.fit("Files area: a.py, b.py, c.py, word\nCreates: c.py\n", "New", {}, ".")
        self.assertEqual(1, len(lines))
        self.assertIn("names b.py", lines[0])

    def test_git_unable_to_read_main_is_said(self):
        with mock.patch.object(intake, "tracked", return_value=None):
            _, lines = intake.fit("Files area: a.py\n", "New", {}, ".")
        self.assertIn("did not run", lines[0])


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
