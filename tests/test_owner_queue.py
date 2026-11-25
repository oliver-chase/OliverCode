"""The owner queue refuses a step with no attempt behind it and summarizes the open steps (#629)."""

import json
import os
import sys
import unittest
from unittest import mock

import contextlib
import io

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner  # noqa: E402


class TestOwnerQueue(unittest.TestCase):
    def test_queue_keeps_real_attempts_and_reports_the_week(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, cmd_owner.command_owner(["summary"]))
                self.assertEqual(1, cmd_owner.command_owner(["add", "--session", "s1", "--step", "Install"]))
                self.assertEqual(1, cmd_owner.command_owner(["add", "--session", "s1", "--step", "x", "--command", "ls"]))
                self.assertEqual(0, cmd_owner.command_owner(
                    ["add", "--session", "s1", "--step", "Enter the key", "--command", "gh auth login", "--error", "refused"]))
                self.assertEqual(0, cmd_owner.command_owner(["add", "--session", "s2", "--step", "Pick a price", "--decision"]))
                self.assertEqual(0, cmd_owner.command_owner(["done", "2"]))
                self.assertEqual(1, cmd_owner.command_owner(["done", "2"]))
            text = cmd_owner.summary()
            self.assertIn("1 open, 2 added and 1 done", text)
            self.assertIn("gh auth login", text)
            self.assertNotIn("Pick a price", text)
            self.assertEqual(2, len(cmd_owner.items()))

    def test_a_session_waiting_on_the_owner_gets_an_owner_title_and_pin_and_loses_them_on_the_answer(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_owner.command_owner(["add", "--session", "b1", "--step", "Pick a price", "--decision"])
                cmd_owner.command_owner(["add", "--session", "b1", "--step", "Sign in", "--command", "gh auth login", "--error", "refused"])
                cmd_owner.command_owner(["add", "--session", "x9", "--step", "Pick", "--decision"])
                cmd_owner.command_owner(["done", "1"])
                first = buf.getvalue()
                cmd_owner.command_owner(["done", "2"])
                cmd_owner.command_owner(["done", "3"])
            out = buf.getvalue()
        self.assertIn('set_session_title for b1 with "Owner ·" in front of its current title', first)
        self.assertIn("set_pinned for b1 with pinned=true", first)
        self.assertNotIn('for b1 with its title without', first)  # b1 still has step 2 open
        self.assertIn('for b1 with its title without the "Owner ·" prefix', out)
        self.assertIn("set_pinned for b1 with pinned=false", out)
        self.assertIn('for x9 with its title without the "Owner ·" prefix', out)
        self.assertIn("set_pinned for x9 with pinned=false", out)


class TestReadableList(unittest.TestCase):
    def test_steps_that_differ_only_in_a_path_become_one_line_with_their_numbers(self):
        """#1177: stale worktrees read as one line, and an unlike step keeps its own."""
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}):
            for n in (1, 2, 3):
                cmd_owner.add("maintain", f"maintain health: /Users/x/_worktrees/OliverCode-{n} runs commit hooks older than origin/main")
            cmd_owner.add("maintain", "maintain health: python3 is 3.9")
            text = cmd_owner.listing([i for i in cmd_owner.items() if i["status"] == "open"])
        self.assertIn("3 like this", text)
        self.assertIn("(#1, #2, #3)", text)
        self.assertIn("python3 is 3.9", text)
        self.assertTrue(text.startswith("4 things waiting on you"))


class TestQuietQueue(unittest.TestCase):
    def test_the_same_ask_is_held_once_and_counts_its_repeats(self):
        """#1205: a repeat keeps one open step and counts it; an info line is not an open step; a done step can be raised again."""
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}):
            first = cmd_owner.add("conform", "repo: hooks needs the owner", command="fix", error="stopped")
            again = cmd_owner.add("conform", "repo: hooks needs the owner", command="fix", error="stopped")
            cmd_owner.note("groom", "an info line")
            self.assertEqual(first["id"], again["id"])
            open_items = [i for i in cmd_owner.items() if i["status"] == "open"]
            self.assertEqual((1, 2), (len(open_items), open_items[0]["repeats"]))
            cmd_owner.close(first["id"])
            self.assertNotEqual(first["id"], cmd_owner.add("conform", "repo: hooks needs the owner", command="fix", error="stopped")["id"])


class TestPreparedOwnerSteps(unittest.TestCase):
    def run_cmd(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cmd_owner.command_owner(list(argv))
        return code, buf.getvalue()

    def test_a_prepared_step_names_its_tab_and_what_happens_after_submit(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            code, _ = self.run_cmd("add", "--session", "s1", "--step", "Create the Kit account",
                                   "--tab", "https://example.test/signup", "--after", "queues the first reminder",
                                   "--check", "the account API endpoint")
            self.assertEqual(0, code)
            _, listed = self.run_cmd("list")
            self.assertIn("https://example.test/signup", listed)
            self.assertIn("queues the first reminder", listed)
            code, closed = self.run_cmd("done", "1")
            self.assertEqual(0, code)
            self.assertIn("Resume: check the result in the account API endpoint", closed)
            self.assertIn("queues the first reminder", closed)

    def test_a_secret_or_a_half_prepared_step_is_refused_and_nothing_is_written(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            for argv in (["--step", "Sign up", "--tab", "https://x.test", "--after", "go on", "--check", "password=hunter2"],
                         ["--step", "Pay with 4242 4242 4242 4242", "--tab", "https://x.test", "--after", "go on"],
                         ["--step", "Sign up", "--tab", "https://x.test"],
                         ["--step", "Sign up", "--after", "go on"],
                         ["--step", "Sign up", "--tab", "https://x.test", "--after", "go on", "--decision"],
                         ["--step", "Sign up", "--tab", "https://x.test", "--after", "go on", "--command", "ls", "--error", "no"]):
                code, out = self.run_cmd("add", "--session", "s1", *argv)
                self.assertEqual(1, code, argv)
                self.assertIn("Refused", out)
            self.assertEqual([], cmd_owner.items())

    def test_a_step_naming_a_repo_that_ends_in_code_is_queued(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            item = cmd_owner.add("maintain", "branches: OliverCode: 1 unmerged branch(es) older than 24 hours with no worktree: story/594")
            self.assertEqual("open", item["status"])
            self.assertEqual(1, len(cmd_owner.items()))

    def test_a_keyword_secret_is_refused_whatever_its_case_or_prefix(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            for step in ("verification code: 123456", "OTP code: 4411", "passcode: 99182", "api_key=abc123", "my_password: hunter2"):
                with self.assertRaisesRegex(ValueError, "a step never holds a password, card number, key or code"):
                    cmd_owner.add("s1", step)
            self.assertEqual([], cmd_owner.items())

    def test_a_command_step_still_resumes_with_no_tab_line(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            self.run_cmd("add", "--session", "s1", "--step", "Key", "--command", "gh auth login", "--error", "refused")
            _, closed = self.run_cmd("done", "1")
            self.assertNotIn("Resume:", closed)


class TestOwnerNotification(unittest.TestCase):
    def raise_step(self, session="drain", step="Story 7 needs your answer", platform="darwin", on=True, times=1):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_owner.sys, "platform", platform), \
                mock.patch.object(cmd_owner.local_config, "setting", return_value=on), \
                mock.patch.object(cmd_owner.subprocess, "run") as run:
            for _ in range(times):
                cmd_owner.add(session, step, "ls", "refused")
            return run, cmd_owner.listing(cmd_owner.items())

    def test_a_new_drain_step_sends_one_notification_with_its_text(self):
        run, _ = self.raise_step()
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual("osascript", argv[0])
        self.assertIn("Story 7 needs your answer", argv[2])

    def test_the_same_step_raised_again_sends_no_second_notification(self):
        run, _ = self.raise_step(times=2)
        self.assertEqual(1, run.call_count)

    def test_housekeeping_steps_send_nothing_and_still_list(self):
        for session in ("conform", "maintain", "groom"):
            run, listed = self.raise_step(session=session)
            run.assert_not_called()
            self.assertIn("Story 7 needs your answer", listed)

    def test_setting_off_or_not_a_mac_sends_nothing_and_still_lists(self):
        for kwargs in ({"on": False}, {"platform": "linux"}):
            run, listed = self.raise_step(**kwargs)
            run.assert_not_called()
            self.assertIn("Story 7 needs your answer", listed)

    def test_the_only_process_started_is_osascript(self):
        run, _ = self.raise_step(step='Quote "this" \\ path')
        self.assertEqual({"osascript"}, {c.args[0][0] for c in run.call_args_list})
        self.assertIn('\\"this\\" \\\\ path', run.call_args.args[0][2])


if __name__ == "__main__":
    unittest.main()
