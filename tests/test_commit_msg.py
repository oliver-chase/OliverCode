"""The commit-msg hook blocks a commit with no story reference, in a scratch repo."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo

HOOK = REPO_ROOT / "core" / "templates" / "project" / "commit-msg"


class TestCommitMsg(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-commitmsg-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        scratch_repo(self.repo)
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        shutil.copy2(HOOK, hooks / "commit-msg")
        git(self.repo, "config", "core.hooksPath", ".githooks")
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "a.txt")

    def commit(self, message, *extra):
        (self.repo / "a.txt").write_text(message + "\n")
        git(self.repo, "add", "a.txt")
        return git(self.repo, "commit", "-m", message, *extra, check=False)

    def first_commit(self):
        """The initial commit is exempt, so most tests start from a repo with a history."""
        git(self.repo, "commit", "-m", "first commit with no reference")

    def test_the_initial_commit_is_exempt(self):
        self.assertEqual(0, git(self.repo, "commit", "-m", "first", check=False).returncode)

    def test_a_commit_without_a_reference_is_blocked(self):
        self.first_commit()
        result = self.commit("Add a feature")
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

    def test_a_reference_in_the_subject_passes(self):
        self.first_commit()
        self.assertEqual(0, self.commit("Add a feature (#53)").returncode)

    def test_a_story_line_in_the_body_passes(self):
        self.first_commit()
        self.assertEqual(0, self.commit("Add a feature\n\nStory: #53").returncode)

    def test_a_hex_colour_is_not_a_reference(self):
        self.first_commit()
        self.assertEqual(1, self.commit("Use colour #123abc").returncode)

    def test_a_bare_hash_is_not_a_reference(self):
        self.first_commit()
        self.assertEqual(1, self.commit("Fix the # sign").returncode)

    def test_revert_fixup_and_squash_messages_are_exempt(self):
        self.first_commit()
        for message in ('Revert "Add a feature"', "fixup! Add a feature", "squash! Add a feature",
                        "Merge branch 'x'"):
            with self.subTest(message=message):
                self.assertEqual(0, self.commit(message).returncode)

    def test_a_message_that_opens_with_a_reference_passes(self):
        self.first_commit()
        self.assertEqual(0, self.commit("#53 fix").returncode)

    def test_a_reference_line_in_an_m_message_is_kept_by_git_and_counts(self):
        self.first_commit()
        result = self.commit("Add a feature\n#53 is the story")
        self.assertEqual(0, result.returncode)
        self.assertIn("#53", git(self.repo, "log", "-1", "--format=%B").stdout)

    def test_a_reference_must_be_a_standalone_token(self):
        self.first_commit()
        for message in ("Fix 5#3", "Fix a#53", "Fix x#53b", "Entity &#39; here"):
            with self.subTest(message=message):
                self.assertEqual(1, self.commit(message).returncode)
        for message in ("Fix (#53)", "Fix org/repo#53", "Fix #53.", "Fix #53, #54"):
            with self.subTest(message=message):
                self.assertEqual(0, self.commit(message).returncode)

    def test_zero_is_not_a_story(self):
        self.first_commit()
        for message in ("Fix #0", "Fix (#000)"):
            with self.subTest(message=message):
                self.assertEqual(1, self.commit(message).returncode)

    def test_an_editor_comment_line_is_dropped_by_git_so_it_does_not_count(self):
        self.first_commit()
        editor = self.repo / "editor.sh"
        editor.write_text('#!/bin/sh\n{ printf "Add a feature\\n# Story: #53\\n"; cat "$1"; } > "$1.new"\nmv "$1.new" "$1"\n')
        editor.chmod(0o755)
        (self.repo / "a.txt").write_text("edited\n")
        git(self.repo, "add", "a.txt")
        env = dict(git_env(), GIT_EDITOR=str(editor))
        result = subprocess.run(["git", "commit"], cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

    def test_an_editor_message_with_a_real_reference_passes(self):
        self.first_commit()
        editor = self.repo / "editor.sh"
        editor.write_text('#!/bin/sh\n{ printf "Add a feature (#53)\\n"; cat "$1"; } > "$1.new"\nmv "$1.new" "$1"\n')
        editor.chmod(0o755)
        (self.repo / "a.txt").write_text("edited\n")
        git(self.repo, "add", "a.txt")
        env = dict(git_env(), GIT_EDITOR=str(editor))
        result = subprocess.run(["git", "commit"], cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_an_unreadable_message_file_fails_closed(self):
        result = self.run_hook(str(self.repo / "nope"))
        self.assertEqual(1, result.returncode)
        self.assertIn("cannot read", result.stdout)

    def run_hook(self, *args):
        return subprocess.run(["bash", str(self.repo / ".githooks" / "commit-msg"), *args],
                              cwd=self.repo, env=git_env(), capture_output=True, text=True)

    def test_no_message_argument_fails_closed(self):
        self.assertEqual(1, self.run_hook().returncode)

    def test_the_owner_override_file_turns_the_check_off_loudly(self):
        self.first_commit()
        (self.repo / ".githooks" / "commit-msg.optout").write_text("")
        result = self.commit("Add a feature")
        self.assertEqual(0, result.returncode)
        self.assertIn("check is off", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
