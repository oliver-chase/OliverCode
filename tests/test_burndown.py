"""`olivercode board burndown`: open issue counts per repo with the change since the last run, a log, and a notification only on a change."""

import contextlib
import io
import os
import plistlib
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_burndown, launchd  # noqa: E402


class TestBurndown(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent = []

    def run_once(self, counts, repos=("o/a", "o/b")):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cmd_burndown.run(repos=lambda: list(repos), count=lambda slug: counts.get(slug), push=self.sent.append, clock=lambda: 1_800_000_000)
        return code, out.getvalue()

    def test_the_first_run_prints_counts_and_sends_nothing(self):
        code, out = self.run_once({"o/a": 5, "o/b": 2})
        self.assertEqual(0, code)
        self.assertIn("o/a: 5 open", out)
        self.assertEqual([], self.sent)
        self.assertIn("o/a: 5 open; o/b: 2 open", (self.home / "burndown.log").read_text())

    def test_a_changed_count_prints_its_delta_and_sends_one_line(self):
        self.run_once({"o/a": 5, "o/b": 2})
        _, out = self.run_once({"o/a": 4, "o/b": 2})
        self.assertIn("o/a: 4 open (-1 since the last run)", out)
        self.assertIn("o/b: 2 open\n", out)
        self.assertEqual(["Open issues changed: a 4 (-1)"], self.sent)

    def test_an_unchanged_run_sends_nothing_and_an_unread_repo_keeps_its_last_count(self):
        self.run_once({"o/a": 5, "o/b": 2})
        _, out = self.run_once({"o/a": 5})
        self.assertIn("o/b: not read", out)
        self.assertEqual([], self.sent)
        _, out = self.run_once({"o/a": 5, "o/b": 3})
        self.assertIn("o/b: 3 open (+1 since the last run)", out)

    def test_the_day_line_counts_open_stories_across_the_repos_read(self):
        day = time.strftime("%Y-%m-%d", time.localtime(1_800_000_000))
        _, out = self.run_once({"o/a": 5, "o/b": 2})
        self.assertIn(f"{day}: 7 open stories across 2 repos, tokens per closed story not recorded by day, "
                      "threads typed into not recorded by day", out)

    def test_a_bad_argument_prints_the_usage_and_no_call_runs(self):
        with mock.patch.object(cmd_burndown, "run", side_effect=AssertionError("ran")), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, cmd_burndown.command_burndown(["--now"]))
        self.assertIn("Usage", out.getvalue())

    def test_the_count_comes_from_the_issues_list_api_never_search_and_a_hold_skips_it(self):
        with mock.patch.object(cmd_burndown.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_burndown.issue_count, "count_issues", return_value=7) as count:
            self.assertEqual(7, cmd_burndown.fetch("o/a"))
        count.assert_called_once_with("o/a", "open")
        with mock.patch.object(cmd_burndown.gh_budget, "refusal", return_value="held"), \
                mock.patch.object(cmd_burndown.issue_count, "count_issues") as count:
            self.assertIsNone(cmd_burndown.fetch("o/a"))
        count.assert_not_called()

    def test_the_schedule_names_the_interpreter_newer_python_returns(self):
        home = temp_dir(self)
        with mock.patch.object(launchd.Path, "home", return_value=home), mock.patch.object(launchd.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(launchd, "newer_python", return_value="/opt/py/python3.13"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_burndown.schedule(True))
        plist = plistlib.loads((home / "Library" / "LaunchAgents" / f"{cmd_burndown.LABEL}.plist").read_bytes())
        self.assertEqual("/opt/py/python3.13", plist["ProgramArguments"][0])


if __name__ == "__main__":
    unittest.main()
