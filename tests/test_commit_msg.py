"""The commit-msg hook blocks a commit with no story reference, in a scratch repo."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, git_env, scratch_repo, temp_dir

HOOK = REPO_ROOT / "core" / "templates" / "project" / "commit-msg"


class CommitMsgCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One scratch repo per class with the hook installed and a.txt staged; each test copies it."""
        cls._template = Path(tempfile.mkdtemp(prefix="olivercode-commitmsg-template-"))
        cls.addClassCleanup(shutil.rmtree, cls._template, ignore_errors=True)
        scratch_repo(cls._template)
        hooks = cls._template / ".githooks"
        hooks.mkdir()
        shutil.copy2(HOOK, hooks / "commit-msg")
        git(cls._template, "config", "core.hooksPath", ".githooks")
        (cls._template / "a.txt").write_text("a\n")
        git(cls._template, "add", "a.txt")

    def setUp(self):
        self.repo = temp_dir(self, "olivercode-commitmsg-") / "repo"
        shutil.copytree(self._template, self.repo, symlinks=True)

    def commit(self, message, *extra):
        (self.repo / "a.txt").write_text(message + "\n")
        git(self.repo, "add", "a.txt")
        return git(self.repo, "commit", "-m", message, *extra, check=False)

    def first_commit(self):
        """The initial commit is exempt, so most tests start from a repo with a history."""
        git(self.repo, "commit", "-m", "first commit with no reference")

    def in_merge(self):
        """Puts the repo in the state git is in while it commits a merge, with MERGE_HEAD set."""
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        (self.repo / ".git" / "MERGE_HEAD").write_text(head + "\n")


class TestCommitMsg(CommitMsgCase):
    def test_a_code_change_needs_a_test_change_or_a_stated_reason(self):
        self.first_commit()
        for rel, text in (("tool.py", "x = 1\n"), ("run.sh", "echo hi\n"), ("app.swift", "let x = 1\n"), ("bin/tool", "echo hi\n")):
            with self.subTest(rel):
                (self.repo / rel).parent.mkdir(exist_ok=True)
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
        for rel in ("docs/guide.md", "data.csv", "page.html", "LICENSE"):
            with self.subTest(rel):
                (self.repo / rel).parent.mkdir(exist_ok=True)
                (self.repo / rel).write_text("x\n")
                git(self.repo, "add", rel)
                self.assertEqual(0, git(self.repo, "commit", "-m", "Docs only (#5)", check=False).returncode)
        self.assertEqual(0, self.commit("Docs only (#5)").returncode)

    def test_a_check_script_under_scripts_is_its_own_test(self):
        self.first_commit()
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "live-check.mjs").write_text("process.exit(0)\n")
        git(self.repo, "add", "scripts/live-check.mjs")
        self.assertEqual(0, git(self.repo, "commit", "-m", "Add a live check (#5)", check=False).returncode)
        (self.repo / "scripts" / "build.mjs").write_text("process.exit(0)\n")
        git(self.repo, "add", "scripts/build.mjs")
        self.assertEqual(1, git(self.repo, "commit", "-m", "Add a build (#5)", check=False).returncode)

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

    def test_a_voice_finding_prints_as_a_warning_and_never_blocks(self):
        self.first_commit()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "VOICE.md").write_text("voice\n")
        for bad in ("Work (#5)\n\n- did a thing.", "Use the cache rather than the API (#5)",
                    "Work (#5)\n\nIt is a guide, not a rule."):
            with self.subTest(bad):
                result = self.commit(bad)
                self.assertEqual(0, result.returncode)
                self.assertIn("WARNING", result.stdout + result.stderr)
                self.assertIn("voice", result.stdout + result.stderr)
                self.assertNotIn("BLOCKED", result.stdout + result.stderr)
        self.assertNotIn("WARNING", self.commit("Work (#5)\n\n- did a thing\n\nA full sentence ends with a period.").stdout)

    def test_every_blocking_finding_prints_together_before_the_commit_is_refused(self):
        self.first_commit()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "VOICE.md").write_text("voice\n")
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py", "docs")
        result = git(self.repo, "commit", "-m", "Use the cache rather than the API\n\nCo-Authored-By: Claude", check=False)
        out = result.stdout + result.stderr
        self.assertEqual(1, result.returncode)
        for finding in ("names no story", "changes code and no test", "co-author line", "WARNING"):
            self.assertIn(finding, out)
        self.assertIn("3 blocking findings", out)

    def test_a_single_finding_names_itself_once(self):
        self.first_commit()
        result = self.commit("Add a feature")
        self.assertIn("1 blocking finding", result.stdout + result.stderr)
        self.assertNotIn("findings", result.stdout + result.stderr)

    def test_a_repo_without_a_voice_doc_is_not_held_to_the_voice(self):
        self.first_commit()
        self.assertNotIn("voice", self.commit("Use the cache rather than the API (#5)\n\nNo test: text only").stdout)

    def test_the_initial_commit_is_exempt(self):
        self.assertEqual(0, git(self.repo, "commit", "-m", "first", check=False).returncode)

    def test_a_commit_without_a_reference_is_blocked(self):
        self.first_commit()
        result = self.commit("Add a feature")
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

    def test_revert_fixup_and_squash_messages_are_exempt_only_when_they_name_a_commit(self):
        self.first_commit()
        known = "first commit with no reference"
        sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        for message, code in ((f'Revert "{known}"\n\nThis reverts commit {sha}.', 0), (f'Revert "{known}"', 1), (f"fixup! {known}", 0), (f"squash! fixup! {known}", 0),
                              (f"amend! {known}", 0), ('Revert "no such commit"', 1), ("fixup! no such commit", 1)):
            with self.subTest(message=message):
                self.assertEqual(code, self.commit(message).returncode)

    def test_a_config_with_an_empty_owner_notes_that_stories_were_not_checked(self):
        self.first_commit()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text('{"repoOwner": "", "repoName": ""}\n')
        git(self.repo, "add", "docs")
        done = git(self.repo, "commit", "-m", "Add a config (#999999)", check=False)
        self.assertEqual(0, done.returncode)
        self.assertIn("names no repoOwner", done.stdout + done.stderr)

    def test_a_config_for_another_repo_than_origin_is_not_checked(self):
        self.first_commit()
        git(self.repo, "remote", "add", "origin", "git@github.com:second-person/MyCode.git")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text('{"repoOwner": "first-owner", "repoName": "TheirCode"}\n')
        git(self.repo, "add", "docs")
        done = git(self.repo, "commit", "-m", "Add a config (#999999)", check=False)
        self.assertEqual(0, done.returncode)
        self.assertIn("names first-owner/theircode but this checkout's origin is second-person/mycode", done.stdout + done.stderr)

    def test_a_deleted_test_and_code_under_docs_do_not_count_as_a_test(self):
        self.first_commit()
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_old.py").write_text("x = 1\n")
        git(self.repo, "add", "tests")
        self.assertEqual(0, git(self.repo, "commit", "-m", "Add a test (#5)", check=False).returncode)
        git(self.repo, "rm", "-q", "tests/test_old.py")
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py")
        self.assertEqual(1, git(self.repo, "commit", "-m", "Add a tool (#5)", check=False).returncode)
        git(self.repo, "reset", "-q", "--hard")
        (self.repo / "docs" / "tools").mkdir(parents=True)
        (self.repo / "docs" / "tools" / "helper.py").write_text("x = 1\n")
        git(self.repo, "add", "docs")
        self.assertEqual(1, git(self.repo, "commit", "-m", "Add a helper (#5)", check=False).returncode)

    def test_a_fixup_that_names_a_commit_still_needs_a_test_for_its_code(self):
        self.first_commit()
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py")
        result = git(self.repo, "commit", "-m", "fixup! first commit with no reference", check=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("no test", result.stdout + result.stderr)

    def test_a_merge_that_stages_code_is_checked_for_a_story_and_a_test(self):
        self.first_commit()
        self.in_merge()
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py")
        result = git(self.repo, "commit", "-m", "Merge branch 'x'", check=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

    def test_a_subject_that_only_starts_with_merge_is_checked(self):
        self.first_commit()
        self.assertEqual(1, self.commit("Merge the login fix").returncode)
        self.in_merge()
        self.assertEqual(0, self.commit("Merge branch 'x'").returncode)

    def test_a_reference_line_in_a_dash_m_message_is_kept_by_git_and_counts(self):
        self.first_commit()
        result = self.commit("Add a feature\n#53 is the story")
        self.assertEqual(0, result.returncode)
        self.assertIn("#53", git(self.repo, "log", "-1", "--format=%B").stdout)

    def test_a_reference_must_be_a_standalone_token(self):
        self.first_commit()
        # A hex colour, a bare hash and zero are not story references either.
        for message in ("Fix 5#3", "Fix a#53", "Fix x#53b", "Entity &#39; here", "Use colour #123abc",
                        "Fix the # sign", "Fix #0", "Fix (#000)"):
            with self.subTest(message=message):
                self.assertEqual(1, self.commit(message).returncode)
        # A Story line in the body and a message that opens with the reference both count.
        for message in ("Fix (#53)", "Fix org/repo#53", "Fix #53.", "Fix #53, #54", "Add a feature\n\nStory: #53", "#53 fix"):
            with self.subTest(message=message):
                self.assertEqual(0, self.commit(message).returncode)

    def editor_commit(self, line):
        """Commit through an editor that writes `line` above git's template."""
        self.first_commit()
        editor = self.repo / "editor.sh"
        editor.write_text('#!/bin/sh\n{ printf "' + line + '\\n"; cat "$1"; } > "$1.new"\nmv "$1.new" "$1"\n')
        editor.chmod(0o755)
        (self.repo / "a.txt").write_text("edited\n")
        git(self.repo, "add", "a.txt")
        env = dict(git_env(), GIT_EDITOR=str(editor))
        return subprocess.run(["git", "commit"], cwd=self.repo, env=env, capture_output=True, text=True)

    def test_an_editor_comment_line_is_dropped_by_git_so_it_does_not_count(self):
        result = self.editor_commit("Add a feature\\n# Story: #53")
        self.assertEqual(1, result.returncode)
        self.assertIn("names no story", result.stdout + result.stderr)

    def test_an_editor_message_with_a_real_reference_passes(self):
        result = self.editor_commit("Add a feature (#53)")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_an_unreadable_message_file_fails_closed(self):
        result = self.run_hook(str(self.repo / "nope"))
        self.assertEqual(1, result.returncode)
        self.assertIn("cannot read", result.stdout)

    def run_hook(self, *args):
        env = {**git_env(), "OLIVERCODE_FAILURE_LOG": str(self.repo / "failures.log")}  # a refusal the test wants is not the owner's log
        return subprocess.run(["bash", str(self.repo / ".githooks" / "commit-msg"), *args],
                              cwd=self.repo, env=env, capture_output=True, text=True)

    def test_no_message_argument_fails_closed(self):
        self.assertEqual(1, self.run_hook().returncode)

    def test_the_owner_override_file_turns_the_check_off_loudly(self):
        self.first_commit()
        optout = self.repo / ".githooks" / "commit-msg.optout"
        optout.write_text("")
        # An untracked file, or one only staged, does not turn the checks off.
        self.assertEqual(1, self.commit("Add a feature").returncode)
        git(self.repo, "add", "-f", ".githooks/commit-msg.optout")
        self.assertEqual(1, git(self.repo, "commit", "-m", "Add the opt-out", check=False).returncode)
        git(self.repo, "commit", "-q", "--no-verify", "-m", "Opt out (#5)")
        result = self.commit("Add another feature")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
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
        # a small change (one file, 20 lines or fewer, no behavior) files no story and cites its open epic, which is an issue like any other
        self.assertEqual(0, self.commit("Fix a typo in one doc (epic #12)").returncode)
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

    def test_a_placeholder_config_passes_and_says_how_to_fill_it(self):
        (self.repo / "docs" / "backlog-config.json").write_text('{"repoOwner": "your-github-owner", "repoName": "your-repo"}\n')
        done = self.commit("Add a feature (#99)")
        self.assertEqual(0, done.returncode)
        self.assertIn("still holds placeholders", done.stdout + done.stderr)
        self.assertEqual([], self.calls())


class TestCommitMsgEdges(CommitMsgCase):
    def test_a_merge_that_stages_no_code_is_exempt_from_the_checks(self):
        self.first_commit()
        self.in_merge()
        self.assertEqual(0, self.commit("Merge branch 'use-x-instead-of-y'").returncode)


class TestCommitCheck(CommitMsgCase):
    """`olivercode commit-check FILE_OR_TEXT` (scripts/lib/cmd_commit_check.py) runs the same checks on a draft, in the current repo, and prints every finding."""

    def check(self, draft):
        cli = REPO_ROOT / "scripts" / "olivercode"
        env = {k: v for k, v in os.environ.items() if k != "OLIVERCODE_FAILURE_LOG"}
        return subprocess.run([sys.executable, str(cli), "commit-check", draft], cwd=self.repo, capture_output=True, text=True, env=env)

    def test_a_draft_text_prints_every_blocking_finding_and_exits_non_zero(self):
        self.first_commit()
        (self.repo / "tool.py").write_text("x = 1\n")
        git(self.repo, "add", "tool.py")
        done = self.check("Add a tool\n\nCo-Authored-By: Claude")
        out = done.stdout + done.stderr
        self.assertEqual(1, done.returncode)
        for finding in ("names no story", "changes code and no test", "co-author line"):
            self.assertIn(finding, out)
        self.assertEqual("", git(self.repo, "log", "-1", "--format=%s", "--grep", "Add a tool").stdout.strip(), "a check commits nothing")

    def test_a_draft_file_is_read_and_a_clean_draft_exits_zero(self):
        self.first_commit()
        draft = self.repo / "draft.txt"
        draft.write_text("Add a thing (#5)\n")
        done = self.check(str(draft))
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("no blocking findings", done.stdout)

    def test_a_voice_finding_in_a_draft_is_a_warning_and_exits_zero(self):
        self.first_commit()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "VOICE.md").write_text("voice\n")
        done = self.check("Use the cache rather than the API (#5)")
        self.assertEqual(0, done.returncode)
        self.assertIn("WARNING", done.stdout)

    def test_a_check_logs_no_refusal_and_queues_no_card(self):
        self.first_commit()
        log = self.repo / "failures.log"
        env = {**os.environ, "OLIVERCODE_FAILURE_LOG": str(log)}
        cli = REPO_ROOT / "scripts" / "olivercode"
        subprocess.run([sys.executable, str(cli), "commit-check", "Add a feature closes #5"], cwd=self.repo, capture_output=True, text=True, env=env)
        done = subprocess.run([sys.executable, str(cli), "commit-check", "No story at all"], cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(1, done.returncode)
        self.assertFalse(log.exists() and log.read_text().strip(), "a draft check is not a refusal")
