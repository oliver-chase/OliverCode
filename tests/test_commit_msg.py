"""The commit-msg hook: one table of message and staged diff against the verdict, run through the real hook."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `-m unittest tests.test_commit_msg` finds _support
from _support import REPO_ROOT, git, git_env, scratch_repo, temp_dir  # noqa: E402

HOOK = REPO_ROOT / "core" / "templates" / "project" / "commit-msg"
CLI = REPO_ROOT / "scripts" / "olivercode"
FIRST = "first commit with no reference"
VOICE = {"docs/VOICE.md": "voice\n"}
TOOL = {"tool.py": "x = 1\n"}
GOOD_CO = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def setUpModule():
    """One scratch repo with the hook installed and a first commit holding a.txt and a test; each test copies it."""
    CommitMsgCase._template = template = Path(tempfile.mkdtemp(prefix="olivercode-commitmsg-template-"))
    unittest.addModuleCleanup(shutil.rmtree, template, ignore_errors=True)
    scratch_repo(template)
    (template / ".githooks").mkdir()
    shutil.copy2(HOOK, template / ".githooks" / "commit-msg")
    git(template, "config", "core.hooksPath", ".githooks")
    (template / "a.txt").write_text("a\n")
    (template / "tests").mkdir()
    (template / "tests" / "test_old.py").write_text("x = 1\n")
    git(template, "add", "a.txt", "tests")
    git(template, "commit", "-q", "-m", FIRST)


# (message, staged files, exit code, words the output holds; a word that starts with "!" must be absent).
# A file staged as None is deleted. "{sha}" is the first commit. MERGE as a file puts the repo mid-merge.
MERGE = "MERGE_HEAD"
TABLE = [
    # STORY-REF-1: a reference is a standalone # and a positive number.
    ("Add a feature", {}, 1, ["names no story", "1 blocking finding", "!findings"]),
    *[(m, {}, 1, ["names no story"]) for m in ("Fix 5#3", "Fix a#53", "Fix x#53b", "Entity &#39; here",
                                                "Use colour #123abc", "Fix the # sign", "Fix #0", "Fix (#000)")],
    *[(m, {}, 0, []) for m in ("Fix (#53)", "Fix org/repo#53", "Fix #53.", "Fix #53, #54", "Add a feature\n\nStory: #53", "#53 fix")],
    # A revert or autosquash is exempt only when it names a commit that exists, and still needs a test for its code.
    (f'Revert "{FIRST}"\n\nThis reverts commit {{sha}}.', {}, 0, []),
    (f'Revert "{FIRST}"', {}, 1, []),
    ('Revert "no such commit"', {}, 1, []),
    (f"fixup! {FIRST}", {}, 0, []),
    (f"squash! fixup! {FIRST}", {}, 0, []),
    (f"amend! {FIRST}", {}, 0, []),
    ("fixup! no such commit", {}, 1, []),
    (f"fixup! {FIRST}", TOOL, 1, ["no test"]),
    # A subject that starts with "Merge" is a merge only when MERGE_HEAD is set, and a merge that stages code is checked.
    ("Merge the login fix", {}, 1, []),
    ("Merge branch 'use-x-instead-of-y'", {MERGE: ""}, 0, []),
    ("Merge branch 'x'", {MERGE: "", **TOOL}, 1, ["names no story"]),
    # A co-author line has one form, and merges are checked too.
    (f"Work (#5)\n\n{GOOD_CO}", {}, 0, []),
    *[(f"Merge branch x (#5)\n\n{bad}", {}, 1, ["Co-Authored-By"]) for bad in (
        "Co-authored-by: Claude <noreply@anthropic.com>", "Co-Authored-By: Claude <claude@anthropic.com>",
        "co-authored-by: Jane Doe <jane@example.invalid>", "Co-Authored-By: Claude")],
    # A code change needs a test change or a stated reason. A check script under scripts/ is its own test, and a
    # deleted test or code under docs/ is not a test.
    *[("Add a tool (#5)", {rel: "x\n"}, 1, ["no test"]) for rel in ("tool.py", "run.sh", "app.swift", "bin/tool", "scripts/build.mjs", "docs/tools/helper.py")],
    ("Add a tool (#5)\n\nNo test: a constant with no behavior", TOOL, 0, []),
    ("Change the tool (#5)", {**TOOL, "tests/test_tool.py": "import tool\n"}, 0, []),
    ("Add a tool (#5)", {**TOOL, "tests/test_old.py": None}, 1, ["no test"]),
    *[("Docs only (#5)", {rel: "x\n"}, 0, []) for rel in ("docs/guide.md", "data.csv", "page.html", "LICENSE", "scripts/live-check.mjs")],
    # VOICE-1 warns and never blocks, and only in a repo with docs/VOICE.md.
    *[(m, VOICE, 0, ["WARNING", "voice", "!BLOCKED"]) for m in (
        "Work (#5)\n\n- did a thing.", "Use the cache rather than the API (#5)", "Work (#5)\n\nIt is a guide, not a rule.")],
    ("Work (#5)\n\n- did a thing\n\nA full sentence ends with a period.", VOICE, 0, ["!WARNING"]),
    ("Use the cache rather than the API (#5)", {}, 0, ["!voice"]),
    # Every blocking finding prints together before the commit is refused.
    ("Use the cache rather than the API\n\nCo-Authored-By: Claude", {**VOICE, **TOOL}, 1,
     ["names no story", "changes code and no test", "co-author line", "WARNING", "3 blocking findings"]),
]


class CommitMsgCase(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self, "olivercode-commitmsg-") / "repo"
        shutil.copytree(self._template, self.repo, symlinks=True)

    def stage(self, files):
        for rel, text in files.items():
            if rel == MERGE:
                (self.repo / ".git" / MERGE).write_text(git(self.repo, "rev-parse", "HEAD").stdout)
            elif text is None:
                git(self.repo, "rm", "-q", rel)
            else:
                (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.repo / rel).write_text(text)
                git(self.repo, "add", rel)

    def hook(self, *args, **env):
        """Run the installed hook as git does; a refusal the test wants is not the owner's log."""
        env = {**git_env(), "OLIVERCODE_FAILURE_LOG": str(self.repo / "failures.log"), **env}
        done = subprocess.run(["bash", str(self.repo / ".githooks" / "commit-msg"), *args],
                              cwd=self.repo, env=env, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def verdict(self, message, **env):
        msg = self.repo / ".git" / "COMMIT_EDITMSG"
        msg.write_text(message + "\n")
        return self.hook(str(msg), **env)

    def commit(self, message, *extra):
        (self.repo / "a.txt").write_text(message + "\n")
        git(self.repo, "add", "a.txt")
        return git(self.repo, "commit", "-m", message, *extra, check=False)


class TestCommitMsg(CommitMsgCase):
    def test_each_message_and_diff_gets_its_verdict(self):
        sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        for message, files, code, words in TABLE:
            message = message.replace("{sha}", sha)
            with self.subTest(message=message, files=sorted(files)):
                self.stage(files)
                got, out = self.verdict(message)
                self.assertEqual(code, got, out)
                for word in words:
                    (self.assertNotIn if word.startswith("!") else self.assertIn)(word.lstrip("!"), out)
                git(self.repo, "reset", "-q", "--hard")
                git(self.repo, "clean", "-fdq", "-e", ".githooks")

    def test_a_real_commit_exits_with_the_hooks_verdict_and_the_initial_commit_is_exempt(self):
        self.assertEqual(1, self.commit("Add a feature").returncode)
        done = self.commit("Add a feature\n#53 is the story")  # -m keeps a line that opens with #
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("#53", git(self.repo, "log", "-1", "--format=%B").stdout)
        git(self.repo, "checkout", "-q", "--orphan", "fresh")
        self.assertEqual(0, self.commit("first").returncode)

    def test_an_editor_comment_line_is_dropped_by_git_so_it_does_not_count(self):
        editor = self.repo / "editor.sh"
        env = dict(git_env(), GIT_EDITOR=str(editor))
        for line, code in (("Add a feature\\n# Story: #53", 1), ("Add a feature (#53)", 0)):
            with self.subTest(line):
                editor.write_text('#!/bin/sh\n{ printf "' + line + '\\n"; cat "$1"; } > "$1.new"\nmv "$1.new" "$1"\n')
                editor.chmod(0o755)
                (self.repo / "a.txt").write_text(line + "\n")
                git(self.repo, "add", "a.txt")
                done = subprocess.run(["git", "commit"], cwd=self.repo, env=env, capture_output=True, text=True)
                self.assertEqual(code, done.returncode, done.stdout + done.stderr)
                if code:
                    self.assertIn("names no story", done.stdout + done.stderr)

    def test_an_unreadable_or_missing_message_file_fails_closed(self):
        code, out = self.hook(str(self.repo / "nope"))
        self.assertEqual(1, code)
        self.assertIn("cannot read", out)
        self.assertEqual(1, self.hook()[0])

    def test_the_owner_override_file_turns_the_check_off_loudly(self):
        (self.repo / ".githooks" / "commit-msg.optout").write_text("")
        # An untracked file, or one only staged, does not turn the checks off.
        self.assertEqual(1, self.commit("Add a feature").returncode)
        git(self.repo, "add", "-f", ".githooks/commit-msg.optout")
        self.assertEqual(1, git(self.repo, "commit", "-m", "Add the opt-out", check=False).returncode)
        git(self.repo, "commit", "-q", "--no-verify", "-m", "Opt out (#5)")
        result = self.commit("Add another feature")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("check is off", result.stdout + result.stderr)

    def test_commit_check_runs_the_hook_on_a_draft_commits_nothing_and_logs_no_refusal(self):
        """`olivercode commit-check FILE_OR_TEXT` (scripts/lib/cmd_commit_check.py); the table above owns each finding."""
        log = self.repo / "failures.log"
        env = {**os.environ, "OLIVERCODE_FAILURE_LOG": str(log)}
        check = lambda draft: subprocess.run([sys.executable, str(CLI), "commit-check", draft], cwd=self.repo,  # noqa: E731
                                             capture_output=True, text=True, env=env)
        self.stage(TOOL)
        blocked = check("Add a tool\n\nCo-Authored-By: Claude")
        self.assertEqual(1, blocked.returncode)
        self.assertIn("names no story", blocked.stdout + blocked.stderr)
        self.assertEqual(FIRST, git(self.repo, "log", "-1", "--format=%s").stdout.strip(), "a check commits nothing")
        self.assertFalse(log.exists() and log.read_text().strip(), "a draft check is not a refusal")
        draft = self.repo / "draft.txt"
        draft.write_text("Add a thing (#5)\n\nNo test: a draft\n")
        clean = check(str(draft))
        self.assertEqual(0, clean.returncode, clean.stdout + clean.stderr)
        self.assertIn("no blocking findings", clean.stdout)


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
        self.config('{"repoOwner": "acme", "repoName": "app"}')
        (self.repo / "fakebin").mkdir()
        (self.repo / "fakebin" / "gh").write_text(FAKE_GH)
        (self.repo / "fakebin" / "gh").chmod(0o755)
        self.log = self.repo / "gh.log"
        self.env = {"PATH": f"{self.repo / 'fakebin'}:{os.environ['PATH']}", "FAKE_GH_LOG": str(self.log),
                    "FAKE_GH_OK": "acme/app/issues/12 acme/other/issues/7"}

    def config(self, body):
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs" / "backlog-config.json").write_text(body + "\n")

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_story_numbers_are_checked_against_the_repo_cached_and_skipped_offline(self):
        # A closing keyword (#1045), an epic and owner/repo#N each name an issue, checked against the repo it names.
        for message, code in (("Add a feature (#99)", 1), ("Ship it, closes #99", 1), ("Add a feature (#12)", 0),
                              ("Ship it, closes #12", 0), ("Fix a typo in one doc (epic #12)", 0),
                              ("Fix it (acme/other#7)", 0), ("Fix it (acme/other#12)", 1)):
            with self.subTest(message):
                got, out = self.verdict(message, **self.env)
                self.assertEqual(code, got, out)
                if "#99" in message:
                    self.assertIn("acme/app#99", out)
        self.assertIn("repos/acme/other/issues/12", "\n".join(self.calls()))
        # a yes is cached under .git, so the next commit makes no call
        before = len(self.calls())
        self.assertEqual(0, self.verdict("Again (#12)", **self.env)[0])
        self.assertEqual(before, len(self.calls()))
        self.assertTrue(any((self.repo / ".git").glob("*story*")))
        # a dead network warns and lets the commit through
        code, out = self.verdict("Add a feature (#98)", FAKE_GH_DOWN="1", **self.env)
        self.assertEqual(0, code)
        self.assertIn("WARNING", out)

    def test_a_config_the_hook_cannot_check_against_passes_and_says_why(self):
        git(self.repo, "remote", "add", "origin", "git@github.com:second-person/MyCode.git")
        for body, words in (('{"repoOwner": "your-github-owner", "repoName": "your-repo"}', "still holds placeholders"),
                            ('{"repoOwner": "", "repoName": ""}', "names no repoOwner"),
                            ('{"repoOwner": "first-owner", "repoName": "TheirCode"}',
                             "names first-owner/theircode but this checkout's origin is second-person/mycode")):
            with self.subTest(body):
                self.config(body)
                code, out = self.verdict("Add a feature (#99)", **self.env)
                self.assertEqual(0, code, out)
                self.assertIn(words, out)
        self.assertEqual([], self.calls())
