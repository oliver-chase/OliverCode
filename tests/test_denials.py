"""A step the classifier denied is queued once with its exact command and closed when the owner ran it (#781, #787)."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner, denials  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "denial_watch.py"
DENIED = "Permission for this action has been denied by the auto mode classifier."
LOAD = "launchctl bootstrap gui/501 /Users/me/Library/LaunchAgents/com.olivercode.retro.plist"


class TestDeniedJob(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def open_lines(self):
        return [i for i in cmd_owner.items() if i["status"] == "open"]

    def test_a_denied_load_queues_one_line_with_the_label_and_command_and_a_repeat_queues_none(self):
        self.assertIsNotNone(denials.record(LOAD, DENIED, "s1"))
        self.assertIsNone(denials.record(LOAD, DENIED, "s1"))
        (line,) = self.open_lines()
        self.assertEqual(LOAD, line["command"])
        self.assertIn("com.olivercode.retro", line["step"])

    def test_a_command_that_ran_or_is_not_covered_queues_nothing(self):
        self.assertIsNone(denials.record(LOAD, "loaded", "s1"))
        self.assertIsNone(denials.record("ls -la", DENIED, "s1"))
        self.assertEqual([], self.open_lines())

    def test_the_manager_check_closes_the_line_when_the_job_is_loaded(self):
        denials.record(LOAD, DENIED, "s1")
        with mock.patch.object(denials, "_run", return_value=""):
            self.assertEqual(0, denials.close_resolved())
        with mock.patch.object(denials, "_run", return_value="state = running"):
            self.assertEqual(1, denials.close_resolved())
        self.assertEqual([], self.open_lines())

    def test_the_hook_queues_from_a_post_tool_use_payload(self):
        env = {**os.environ, "OLIVERCODE_HOME": str(self.home), "HOME": str(self.home)}
        payload = {"tool_input": {"command": LOAD}, "tool_response": {"stderr": DENIED}, "session_id": "s1", "cwd": "/"}
        done = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env, input=json.dumps(payload))
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn(LOAD, done.stdout)
        self.assertEqual(1, len(self.open_lines()))

    def test_a_denied_git_push_merge_hard_reset_or_rebase_abort_queues_one_line_each(self):
        for verb in ("push origin main", "merge story/1", "reset --hard origin/main", "rebase --abort"):
            self.assertIsNotNone(denials.record(f"git {verb}", DENIED, "s1", "/repo"), verb)
        self.assertEqual(4, len(self.open_lines()))
        self.assertIsNone(denials.record("git push origin main", DENIED, "s1", "/repo"))
        self.assertIsNone(denials.record("git status", DENIED, "s1", "/repo"))
        self.assertIsNone(denials.record("git reset --soft HEAD~1", DENIED, "s1", "/repo"))



if __name__ == "__main__":
    unittest.main()
