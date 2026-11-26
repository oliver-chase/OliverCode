"""The prompt hook prints nothing and keeps the owner's story messages, `lesson add` appends one lesson and
`lesson cover` needs an existing test or an open story."""

import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, quiet, scratch_repo, run_hook, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
from lib import lesson_flags, lessons  # noqa: E402
from lib.cmd_lesson import command_lesson  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "lesson_capture.py"


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


class TestHook(Isolated):
    def test_a_correction_phrase_prints_nothing_and_sets_no_flag(self):
        run = self.hook("I told you to run the tests first. never do that again")
        self.assertEqual((run.returncode, run.stdout), (0, ""))
        self.assertFalse((self.home / "lesson-flags").exists())

    def test_a_message_that_names_a_story_is_not_written_here_and_prints_nothing(self):
        run = self.hook("for #983 you did it wrong again")
        self.assertEqual((run.returncode, run.stdout), (0, ""))
        self.assertEqual([p for p in self.home.rglob("*") if p.is_file()], [])

    def test_the_hook_never_blocks_when_the_home_folder_is_unusable(self):
        blocker = self.home / "blocked"
        blocker.write_text("a file where the folder should go")
        run = self.hook("for #983 never do that", home=blocker)
        self.assertEqual((run.returncode, run.stdout), (0, ""))

    def test_the_hook_is_registered_for_user_prompt_submit(self):
        import claude_settings
        self.assertIn(("UserPromptSubmit", None, "lesson_capture.py"), claude_settings.MANAGED)

    def test_a_lesson_is_appended_by_one_command(self):
        code, out = quiet(command_lesson, ["add", "--repo", str(self.repo), "--what", "w", "--why", "y", "--rule", "r"])
        self.assertEqual(code, 0, out)
        self.assertEqual(1, len(lessons.read(self.repo)))

    def test_only_the_owner_types_a_prompt(self):
        for text in ("<task-notification>never do that again</task-notification>", "<side-sessions-event>wrong</side-sessions-event>"):
            self.assertFalse(lesson_flags.from_owner(text))
        self.assertTrue(lesson_flags.from_owner("never do that"))


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
