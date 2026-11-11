"""The failure log: a blocked commit adds one line holding the date, repo, gate and reason, and the log stays outside git."""

import re
import unittest

from _support import git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401


class TestFailureLog(GateHarness):
    def setUp(self):
        super().setUp()
        self.log = self.tmp.parent / (self.tmp.name + "-failures.log")
        self.addCleanup(lambda: self.log.unlink(missing_ok=True))

    def test_a_blocked_commit_writes_one_line_with_the_gate_and_reason(self):
        self.stage("config.py", 'KEY = "sk-' + "a" * 32 + '"\n')
        self.assertBlocked("gate 1", OLIVERCODE_FAILURE_LOG=str(self.log))
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        when, repo, gate, reason = lines[0].split("\t")
        self.assertRegex(when, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(repo, self.tmp.name)
        self.assertEqual(gate, "Secrets")
        self.assertIn("BLOCKED", reason)

    def test_a_passing_commit_writes_nothing(self):
        self.stage("notes.txt", "Plain notes.\n")
        self.assertAllowed(OLIVERCODE_FAILURE_LOG=str(self.log))
        self.assertFalse(self.log.exists())

    def test_the_log_is_not_inside_the_repo_so_git_never_sees_it(self):
        self.stage("config.py", 'KEY = "sk-' + "b" * 32 + '"\n')
        self.assertBlocked("gate 1", OLIVERCODE_FAILURE_LOG=str(self.log))
        self.assertNotRegex(git(self.tmp, "status", "--short").stdout, re.compile(r"failures"))


if __name__ == "__main__":
    unittest.main()
