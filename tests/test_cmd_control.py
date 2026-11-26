"""CLI tests for owner controls (#1214)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, quiet

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_control, run_lock  # noqa: E402


class ControlCommands(unittest.TestCase):
    def setup_repo(self):
        repo = Path("/repo")
        cfg = {"repoOwner": "owner", "repoName": "sample"}
        patches = [
            mock.patch.object(cmd_control, "resolve_repo", return_value=repo),
            mock.patch.object(cmd_control, "backlog_config", return_value=cfg),
            mock.patch.object(cmd_control, "origin_slug", return_value="owner/sample"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_pause_and_resume(self):
        self.setup_repo()
        with mock.patch.object(run_lock, "pause") as pause, mock.patch.object(run_lock, "resume", return_value=True) as resume:
            code, output = quiet(cmd_control.command_control, ["pause", "sample"])
            self.assertEqual(0, code)
            pause.assert_called_once_with("owner/sample")
            code, output = quiet(cmd_control.command_control, ["resume", "sample"])
            self.assertEqual(0, code)
            resume.assert_called_once_with("owner/sample")

    def test_cancel_only_targets_an_active_story(self):
        self.setup_repo()
        with mock.patch.object(run_lock, "request_cancel", return_value=True) as cancel:
            code, output = quiet(cmd_control.command_control, ["cancel", "sample", "42"])
            self.assertEqual(0, code)
            cancel.assert_called_once_with("owner/sample", 42)
            self.assertIn("Cancellation requested", output)

    def test_bad_arguments_are_refused(self):
        self.assertEqual(2, quiet(cmd_control.command_control, ["cancel", "sample"])[0])
        self.assertEqual(2, quiet(cmd_control.command_control, ["pause"])[0])


if __name__ == "__main__":
    unittest.main()
