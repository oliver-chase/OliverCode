"""The commit-msg hook blocks a commit with no story reference, in a scratch repo."""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo

HOOK = REPO_ROOT / "core" / "templates" / "project" / "commit-msg"


class CommitMsgCase(unittest.TestCase):
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


class TestCommitMsg(CommitMsgCase):
    def test_a_code_change_needs_a_test_change_or_a_stated_reason(self):
        self.first_commit()
        for rel, text in (("tool.py", "x = 1\n"), ("run.sh", "echo hi\n")):
            with self.subTest(rel):
                (self.repo / rel).write_text(text)
                git(self.repo, "add", rel)
                result = git(self.repo, "commit", "-m", "Add a tool (#5)", check=False)
                self.assertEqual(1, result.returncode)
                self.assertIn("no test", result.stdout + result.stderr)
                git(self.repo, "rm", "-q", "--cached", rel)
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py")
        self.assertEqual(0, git(self.repo, "commit", "-m", "Add a tool (#5)\n\nNo test: a constant with no behavior",
                                check=False).returncode)
        (self.repo / "tool.py").write_text("x = 2\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_tool.py").write_text("import tool\n")
        git(self.repo, "add", "tool.py", "tests/test_tool.py")
        self.assertEqual(0, git(self.repo, "commit", "-m", "Change the tool (#5)", check=False).returncode)
        self.assertEqual(0, self.commit("Docs only (#5)").returncode)

    def test_a_co_author_line_has_one_form(self):
        self.first_commit()
        good = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        self.assertEqual(0, self.commit(f"Work (#5)\n\n{good}").returncode)
        self.assertEqual(0, self.commit("Work (#5)").returncode)  # a commit with no co-author passes
        for bad in ("Co-authored-by: Claude <noreply@anthropic.com>", "Co-Authored-By: Claude <claude@anthropic.com>",
                    "co-authored-by: Jane Doe <jane@example.invalid>", "Co-Authored-By: Claude"):
            with self.subTest(bad):
                result = self.commit(f"Merge branch x (#5)\n\n{bad}")  # merges are checked too
                self.assertEqual(1, result.returncode)
                self.assertIn("Co-Authored-By", result.stdout + result.stderr)

    def test_the_initial_commit_is_exempt(self):
        self.assertEqual(0, git(self.repo, "commit", "-m", "first", check=False).returncode)

    def test_a_commit_without_a_reference_is_blocked(self):
        self.first_commit()
        result = self.commit("Add a feature")
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

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


FAKE_GH = """#!/bin/sh
# Fake gh: records each call, answers 200 for the issue numbers in $FAKE_GH_OK and 404 for the rest,
# and fails like a dead network when $FAKE_GH_DOWN is set.
echo "$@" >> "$FAKE_GH_LOG"
[ -n "$FAKE_GH_DOWN" ] && { echo "dial tcp: lookup api.github.com: no such host" >&2; exit 1; }
for ok in $FAKE_GH_OK; do
  case "$2" in "repos/$ok") echo "${ok##*/}"; exit 0 ;; esac
done
echo "gh: Not Found (HTTP 404)" >&2
exit 1
"""


class TestStoryExists(CommitMsgCase):
    """STORY-EXISTS-1: the hook checks each cited number against GitHub, for the repo in docs/backlog-config.json."""

    def setUp(self):
        super().setUp()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text('{"repoOwner": "acme", "repoName": "app"}\n')
        self.first_commit()
        self.bin = self.repo / "fakebin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)
        self.log = self.repo / "gh.log"
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_GH_LOG": str(self.log),
                    "FAKE_GH_OK": "acme/app/issues/12 acme/other/issues/7"}

    def commit(self, message, **env):
        with mock.patch.dict(os.environ, {**self.env, **env}):
            return super().commit(message)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_story_numbers_are_checked_against_the_repo_cached_and_skipped_offline(self):
        blocked = self.commit("Add a feature (#99)")
        self.assertEqual(1, blocked.returncode)
        self.assertIn("acme/app#99", blocked.stdout + blocked.stderr)
        self.assertEqual(0, self.commit("Add a feature (#12)").returncode)
        # owner/repo#N is checked against the repo it names
        self.assertEqual(0, self.commit("Fix it (acme/other#7)").returncode)
        self.assertEqual(1, self.commit("Fix it (acme/other#12)").returncode)
        self.assertIn("repos/acme/other/issues/12", "\n".join(self.calls()))
        # a yes is cached under .git, so the next commit makes no call
        before = len(self.calls())
        self.assertEqual(0, self.commit("Again (#12)").returncode)
        self.assertEqual(before, len(self.calls()))
        self.assertTrue(any((self.repo / ".git").glob("*story*")))
        # a dead network warns and lets the commit through
        offline = self.commit("Add a feature (#98)", FAKE_GH_DOWN="1")
        self.assertEqual(0, offline.returncode)
        self.assertIn("WARNING", offline.stdout + offline.stderr)


if __name__ == "__main__":
    unittest.main()
