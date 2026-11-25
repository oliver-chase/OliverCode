"""A GraphQL hold refuses `gh issue` and lets a REST read run (#1039)."""

import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import gh_budget  # noqa: E402
from lib import cmd_dispatch, intake  # noqa: E402


class TestHold(unittest.TestCase):
    def test_a_graphql_hold_refuses_gh_issue_and_lets_a_rest_read_run(self):
        fetch = lambda: {}  # noqa: E731
        gh_budget.note_limit(resources=("graphql",), fetch=fetch)
        with mock.patch.object(cmd_dispatch.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as ran:
            self.assertEqual("ok", cmd_dispatch.gh(["api", "repos/o/r/issues/1"]).stdout)
            self.assertEqual(1, cmd_dispatch.gh(["issue", "view", "1"]).returncode)
            self.assertEqual(1, cmd_dispatch.gh(["api", "graphql", "-f", "query=x"]).returncode)
        self.assertEqual(1, ran.call_count)


class TestParallelDispatch(unittest.TestCase):
    def test_stories_with_overlapping_files_do_not_run_in_parallel(self):
        story1 = {"number": 1, "body": "Files area: scripts/lib/cmd_dispatch.py"}
        story2 = {"number": 2, "body": "Files area: scripts/lib/cmd_dispatch.py"}
        story3 = {"number": 3, "body": "Files area: tests/test_cmd_dispatch.py"}
        self.assertTrue(intake.overlaps(intake.files_area(story1["body"]), intake.files_area(story2["body"])))
        self.assertFalse(intake.overlaps(intake.files_area(story1["body"]), intake.files_area(story3["body"])))


if __name__ == "__main__":
    unittest.main()
