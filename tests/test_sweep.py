"""`olivercode board sweep`: the nightly board sweep queues one line per board, alerts on drift and never reports an unread board clean (#641)."""

import contextlib
import io
import os
import plistlib
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner, cmd_sweep, launchd  # noqa: E402

DRIFT = ("\n2 finding(s) (advisory -- read and judge, never auto-fixed):\n"
         '  - [status-drift] o/r#5 "A": board Todo, issue CLOSED\n'
         '  - [status-drift] o/r#6 "B": open issue not on the board')


class TestSweep(unittest.TestCase):
    def setUp(self):
        home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent = []

    def sweep(self, outputs, refusal=""):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cmd_sweep.run(board_list=lambda: [("Alpha", Path("a.json")), ("Beta", Path("b.json"))][:len(outputs)],
                                 check=lambda config, *d: (1, outputs[0 if config.name == "a.json" else 1]),
                                 push=self.sent.append, refusal=lambda: refusal)
        return code, out.getvalue()

    def test_a_board_with_drift_queues_its_counts_and_sends_one_alert(self):
        code, _ = self.sweep([DRIFT])
        self.assertEqual(1, code)
        self.assertEqual(["Alpha: 1 drifted card(s), 1 missing card(s)"], [i["step"] for i in cmd_owner.items()])
        self.assertEqual(["Board sweep: Alpha: 1 drifted card(s), 1 missing card(s)"], self.sent)

    def test_clean_boards_queue_zero_counts_and_send_nothing(self):
        code, out = self.sweep(["status-drift: clean."] * 2)
        self.assertEqual(0, code)
        self.assertEqual(["Alpha: 0 drifted card(s), 0 missing card(s), clean", "Beta: 0 drifted card(s), 0 missing card(s), clean"],
                         [i["step"] for i in cmd_owner.items()])
        self.assertEqual([], self.sent)

    def test_a_queue_line_needs_no_owner_action(self):
        self.sweep(["status-drift: clean."])
        self.assertEqual([], [i for i in cmd_owner.items() if i["status"] == "open"])

    def test_a_budget_hold_says_the_sweep_did_not_run_and_never_reports_clean(self):
        with mock.patch.object(cmd_sweep, "hygiene", side_effect=AssertionError("read")):
            code, _ = self.sweep(["status-drift: clean."], refusal="GitHub has 40 GraphQL points left. Queue it.")
        step = cmd_owner.items()[0]["step"]
        self.assertIn("did not run", step)
        self.assertNotIn("clean", step)
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.sent))

    def test_a_failed_read_is_not_clean(self):
        self.sweep(["The sweep did not run. GitHub is down."])
        step = cmd_owner.items()[0]["step"]
        self.assertIn("did not run", step)
        self.assertNotIn("clean", step)

    def test_the_job_calls_no_model_and_runs_nightly(self):
        text = (REPO_ROOT / "scripts" / "lib" / "cmd_sweep.py").read_text()
        for word in ("anthropic", "claude -p", "openai", "api.anthropic"):
            self.assertNotIn(word, text.lower())
        fake_home = temp_dir(self)
        with mock.patch.object(launchd.subprocess, "run") as run, mock.patch.object(Path, "home", return_value=fake_home):
            run.return_value.returncode = 0
            cmd_sweep.schedule(True)
        plist = plistlib.loads((fake_home / "Library" / "LaunchAgents" / "com.olivercode.sweep.plist").read_bytes())
        self.assertEqual("sweep", plist["ProgramArguments"][-1])
        self.assertEqual({"Hour": 2, "Minute": 30}, plist["StartCalendarInterval"])

    def test_the_command_exits_with_the_sweep_result(self):
        for code in (0, 1):
            with mock.patch.object(cmd_sweep, "run", return_value=code), mock.patch("lib.intake.run", return_value=0) as intake_run:
                self.assertEqual(code, cmd_sweep.command_sweep([]))
            intake_run.assert_called_once()
        with mock.patch.object(cmd_sweep, "run", return_value=0), mock.patch("lib.intake.run", return_value=1):
            self.assertEqual(1, cmd_sweep.command_sweep([]))

    def test_a_bad_argument_prints_the_usage(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, cmd_sweep.command_sweep(["--now"]))
        self.assertIn("Usage", out.getvalue())


if __name__ == "__main__":
    unittest.main()
