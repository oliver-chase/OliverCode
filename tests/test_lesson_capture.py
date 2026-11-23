"""A correction from the owner flags a lesson, `lesson add` clears the flag, health fails on a stale one and
`lesson cover` needs an existing test or an open story."""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, quiet, scratch_repo, run_hook, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
from lib import cmd_health, lesson_flags, lessons  # noqa: E402
from lib.cmd_lesson import command_lesson  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "lesson_capture.py"
DAY = 24 * 3600


class Isolated(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.repo = scratch_repo(temp_dir(self) / "repo")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook(self, prompt, home=None):
        env = {**os.environ, "OLIVERCODE_HOME": str(home or self.home)}
        return run_hook(HOOK, {"prompt": prompt}, env=env)

    def flags(self):
        return list(lesson_flags.folder().glob("*.json")) if lesson_flags.folder().is_dir() else []

    def health_lines(self):
        with mock.patch.object(cmd_health, "_claude_dir", return_value=self.home / "none"):
            code, out = quiet(cmd_health.command_health)
        return code, [l for l in out.splitlines() if "correction" in l]


class TestHook(Isolated):
    def test_a_correction_phrase_sets_a_flag_and_prints_context(self):
        prompt = "I told you to run the tests first. " + "x" * 400
        run = self.hook(prompt)
        self.assertEqual(run.returncode, 0)
        context = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("olivercode lesson add", context)
        (flag,) = self.flags()
        body = json.loads(flag.read_text())
        self.assertIn("told you", body["snippet"].lower())
        self.assertLess(len(body["snippet"]), 100)
        self.assertNotIn("x" * 100, flag.read_text())

    def test_a_prompt_with_no_phrase_sets_nothing(self):
        run = self.hook("please add a test for the parser")
        self.assertEqual((run.stdout, self.flags()), ("", []))

    def test_a_cross_session_message_or_notification_is_not_a_correction(self):
        for prompt in ("<cross-session-message from=a>you did this wrong again", "  <system-notification>never mind",
                       "[system-notification] wrong branch"):
            self.assertEqual(self.hook(prompt).stdout, "", prompt)
        self.assertEqual(self.flags(), [])

    def test_the_hook_fails_open_with_one_stderr_line(self):
        blocker = self.home / "blocked"
        blocker.write_text("a file where the folder should go")
        run = self.hook("never do that", home=blocker)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(len(run.stderr.strip().splitlines()), 1)
        self.assertIn("failed open", run.stderr)

    def test_the_hook_is_registered_for_user_prompt_submit(self):
        import claude_settings
        self.assertIn(("UserPromptSubmit", None, "lesson_capture.py"), claude_settings.MANAGED)


class TestAddAndHealth(Isolated):
    def add(self):
        return quiet(command_lesson, ["add", "--repo", str(self.repo), "--what", "w", "--why", "y", "--rule", "r"])

    def test_lesson_add_clears_only_the_flag_it_answers_and_says_how_many_remain(self):
        lesson_flags.record("never do that", now=time.time() - 60)
        newer = lesson_flags.record("that's not what I asked", now=time.time() - 5)
        self.assertEqual(len(self.flags()), 2)
        code, out = self.add()
        self.assertEqual(code, 0)
        self.assertEqual([f.name for f in self.flags()], [newer.name])
        self.assertIn("1 remain open", out)
        quiet(command_lesson, ["add", "--repo", str(self.repo), "--what", "w", "--why", "y", "--rule", "r", "--flag", newer.stem])
        self.assertEqual(self.flags(), [])

    def test_an_agent_turn_records_no_correction(self):
        for text in ("<task-notification>never do that again</task-notification>", "<side-sessions-event>wrong</side-sessions-event>"):
            self.assertIsNone(lesson_flags.match(text))

    def test_health_fails_on_a_day_old_flag_and_passes_after_a_lesson(self):
        lesson_flags.record("never do that", now=time.time() - DAY - 60)
        code, lines = self.health_lines()
        self.assertEqual(code, 1)
        self.assertTrue(any("[FAIL] 1 owner correction" in l and "olivercode lesson add" in l for l in lines), lines)
        self.add()
        code, lines = self.health_lines()
        self.assertTrue(any("[OK] every owner correction has a lesson" in l for l in lines), lines)

    def test_health_passes_on_a_fresh_flag(self):
        lesson_flags.record("never do that")
        self.assertTrue(any("[OK]" in l for l in self.health_lines()[1]))


class TestCover(Isolated):
    def cover(self, ref, state="OPEN"):
        lid = lessons.add("a", "b", "c", repo=self.repo)["id"]
        with mock.patch("lib.lesson_flags.story_state", return_value=state):
            code, out = quiet(command_lesson, ["cover", lid, ref, "--repo", str(self.repo)])
        return code, out, lessons.read(self.repo)[-1]["covered_by"]

    def test_a_missing_test_path_is_refused(self):
        code, out, covered = self.cover("tests/test_nope.py")
        self.assertEqual((code, covered), (1, None))
        self.assertIn("does not exist", out)

    def test_an_existing_test_path_is_accepted(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_real.py").write_text("")
        self.assertEqual(self.cover("tests/test_real.py")[::2], (0, "tests/test_real.py"))
        nested = self.repo / "skills" / "x" / "scripts"
        nested.mkdir(parents=True)
        (nested / "test_it.py").write_text("")
        self.assertEqual(self.cover("skills/x/scripts/test_it.py")[0], 0)

    def test_a_closed_story_is_refused_and_an_open_one_accepted(self):
        code, out, covered = self.cover("#12", state="CLOSED")
        self.assertEqual((code, covered), (1, None))
        self.assertIn("closed", out)
        self.assertEqual(self.cover("#12", state="OPEN")[::2], (0, "#12"))

    def test_other_text_is_refused(self):
        self.assertEqual(self.cover("scripts/hooks/commit_guard.py")[0], 1)


if __name__ == "__main__":
    unittest.main()


class TestAgentTextIsNotACorrection(Isolated):
    def test_messages_from_other_sessions_and_scheduled_tasks_set_no_flag(self):
        for prompt in ('Another Claude session sent a message:\n<agent-message from="a1">R3. It never checks the exit code',
                       '<agent-message from="a1">the gate never runs',
                       '<scheduled-task name="taps" file="x">Never pass --owner-tap',
                       "Background (from the session that started this one): never search the disk"):
            self.assertEqual(self.hook(prompt).stdout, "", prompt)
        self.assertEqual(self.flags(), [])

    def test_a_correction_only_inside_pasted_text_sets_no_flag(self):
        run = self.hook('do this\n<pasted_content id="b1">\nThe hook never checks the exit code.\n</pasted_content id="b1">')
        self.assertEqual((run.stdout, self.flags()), ("", []))

    def test_the_owners_own_words_beside_a_paste_still_set_a_flag(self):
        run = self.hook('<pasted_content id="b1">all fine here</pasted_content id="b1">\nyou did it wrong again')
        self.assertIn("lesson add", run.stdout)
        (flag,) = self.flags()
        self.assertNotIn("all fine", json.loads(flag.read_text())["snippet"])


class TestDismiss(Isolated):
    def test_dismiss_closes_one_flag_and_logs_the_reason(self):
        old = lesson_flags.record("never do that", now=time.time() - 2 * DAY)
        keep = lesson_flags.record("that's wrong again", now=time.time() - 2 * DAY)
        code, out = quiet(command_lesson, ["dismiss", old.stem, "--reason", "an audit finding, not the owner"])
        self.assertEqual(code, 0, out)
        self.assertEqual([p for p, _ in lesson_flags.open_flags()], [keep])
        (entry,) = [json.loads(l) for l in (lesson_flags.folder() / "dismissed.jsonl").read_text().splitlines()]
        self.assertEqual((entry["flag"], entry["reason"]), (old.name, "an audit finding, not the owner"))
        self.assertEqual(lesson_flags.stale_count(), 1)

    def test_dismiss_without_a_reason_or_with_an_unknown_flag_is_refused(self):
        flag = lesson_flags.record("never do that")
        for argv in (["dismiss", flag.stem], ["dismiss", flag.stem, "--reason", "  "],
                     ["dismiss", "no-such-flag", "--reason", "agent text"]):
            code, out = quiet(command_lesson, argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("FAIL", out)
        self.assertTrue(flag.exists())
        self.assertFalse((lesson_flags.folder() / "dismissed.jsonl").exists())
