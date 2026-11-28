"""The pre-push hook blocks a history rewrite and a secret in any commit the push sends."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git_env, scratch_repo, temp_dir

HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-push"
# Built at runtime so this file never holds a value the secret gates would match.
TOKEN = "ghp_" + "a" * 36
Z, ONES = "0" * 40, "1" * 40
MAIN = "refs/heads/main {sha} refs/heads/main "
# (commits as (file, content), with None for an empty commit whose subject is the name; the ref line git hands the
# hook; env, where None unsets; exit code, or None when only the words matter; words, where "!" must be absent).
HOOK_ROWS = [
    ([("WIP #642: partial commit-msg closes check, not validated", None)], MAIN + "{base}", {}, 1, ["WIP #642", "{short}"]),
    ([("Wipe the cache (#12)", None), ("Add the check (#13)", None)], MAIN + "{base}", {}, 0, []),
    *[([("w.txt", "w\n")], "refs/heads/main {sha} " + ref + " " + Z, {"ALLOW_BRANCH_PUSH": None}, 1,
       ["land it on main", "discard it", "olivercode wip", "ALLOW_BRANCH_PUSH=1"]) for ref in ("refs/heads/wip-x", "refs/heads/story-1")],
    ([("m.txt", "m\n")], MAIN + ONES, {"ALLOW_BRANCH_PUSH": None}, None, ["!not the default branch"]),
    ([("m.txt", "m\n")], f"(delete) {Z} refs/heads/wip-x {{sha}}", {"ALLOW_BRANCH_PUSH": None}, 0, []),
    # A remote commit this clone lacks is still scanned, and is not called a force push.
    ([("s.txt", f"tok={TOKEN}\n")], MAIN + ONES, {"ALLOW_FORCE_PUSH": "1"}, 1, []),
    ([("ok.txt", "fine\n")], MAIN + ONES, {}, None, ["!force-pushed", "!ALLOW_FORCE_PUSH"]),
]


class PrePush(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One remote and one clone, built once and copied for each test."""
        cls._template = Path(tempfile.mkdtemp(prefix="pre-push-template-"))
        cls.env = git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                          GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com", ALLOW_BRANCH_PUSH="1")
        remote = scratch_repo(cls._template / "remote.git", bare=True)
        work = scratch_repo(cls._template / "work", branch="main", identity=False)
        (work / "a.txt").write_text("a\n")
        for args in (("add", "a.txt"), ("commit", "-q", "-m", "a.txt"),
                     ("remote", "add", "origin", str(remote)), ("push", "-q", "origin", "main")):
            subprocess.run(["git", *args], cwd=work, env=cls.env, check=True, capture_output=True)
        # Gate 3 needs a launcher; this one reports a passing validation, since these tests cover Gates 0 to 3.
        launcher = cls._template / "olivercode"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o755)
        cls.env["OLIVERCODE_LAUNCHER"] = str(launcher)
        hook = work / ".git" / "hooks" / "pre-push"
        shutil.copy(HOOK, hook)
        hook.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._template, ignore_errors=True)

    def setUp(self):
        self.tmp = temp_dir(self, "pre-push-")
        shutil.copytree(self._template / "remote.git", self.tmp / "remote.git", symlinks=True)
        shutil.copytree(self._template / "work", self.tmp / "work", symlinks=True)
        self.remote = self.tmp / "remote.git"
        self.work = self.tmp / "work"
        self.git("remote", "set-url", "origin", str(self.remote))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.work, env=self.env,
                              capture_output=True, text=True)

    def commit(self, name, content):
        (self.work / name).write_text(content)
        self.git("add", name)
        self.git("commit", "-q", "-m", name)

    def push(self, *args):
        result = self.git("push", "origin", *args)
        # The hook prints to stdout and git prints to stderr; the tests read both.
        result.output = result.stdout + result.stderr
        return result

    def run_hook(self, lines, **env):
        hook = self.work / ".git" / "hooks" / "pre-push"
        env = {k: v for k, v in {**self.env, **env}.items() if v is not None}
        done = subprocess.run([str(hook), "origin", str(self.remote)], cwd=self.work, env=env, input=lines, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def test_each_ref_line_gets_its_verdict(self):
        for commits, line, env, code, words in HOOK_ROWS:
            with self.subTest(line=line, commits=commits):
                self.setUp()
                for name, content in commits:
                    if content is None:
                        self.git("commit", "-q", "--allow-empty", "-m", name)
                    else:
                        self.commit(name, content)
                sha = self.git("rev-parse", "HEAD").stdout.strip()
                base = self.git("rev-parse", f"HEAD~{len(commits)}").stdout.strip()
                got, out = self.run_hook(line.format(sha=sha, base=base) + "\n", **env)
                if code is not None:
                    self.assertEqual(code, 0 if got == 0 else 1, out)
                for word in words:
                    word = word.replace("{short}", sha[:7])
                    (self.assertNotIn if word.startswith("!") else self.assertIn)(word.lstrip("!"), out)

    def test_a_real_push_of_a_refspec_to_a_work_branch_is_refused(self):
        self.commit("w.txt", "w\n")
        self.env.pop("ALLOW_BRANCH_PUSH")
        try:
            result = self.push("HEAD:refs/heads/wip-x")
        finally:
            self.env["ALLOW_BRANCH_PUSH"] = "1"
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertEqual("", self.git("branch", "--list", "wip-x", cwd=self.remote).stdout.strip())

    def test_the_override_pushes_a_branch_and_says_so(self):
        self.commit("w.txt", "w\n")
        result = self.push("HEAD:refs/heads/wip-x")
        self.assertEqual(result.returncode, 0, result.output)
        self.assertIn("ALLOW_BRANCH_PUSH=1 used", result.output)

    def test_a_push_of_main_and_a_branch_delete_pass_the_branch_gate(self):
        self.commit("m.txt", "m\n")
        sha = self.git("rev-parse", "HEAD").stdout.strip()
        code, out = self.run_hook(f"refs/heads/main {sha} refs/heads/main {'1' * 40}\n", ALLOW_BRANCH_PUSH=None)
        self.assertNotIn("not the default branch", out)
        code, out = self.run_hook(f"(delete) {'0' * 40} refs/heads/wip-x {sha}\n", ALLOW_BRANCH_PUSH=None)
        self.assertEqual(code, 0, out)

    def test_a_secret_on_a_new_branch_blocks(self):
        self.git("checkout", "-q", "-b", "feat")
        self.commit("s.txt", f"tok={TOKEN}\n")
        result = self.push("feat")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("potential secret leak", result.output)

    def test_a_secret_added_then_removed_inside_the_range_blocks(self):
        self.commit("s.txt", f"tok={TOKEN}\n")
        self.commit("s.txt", "tok=gone\n")
        result = self.push("main")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("potential secret leak", result.output)

    def test_a_secret_added_in_a_merge_resolution_blocks(self):
        self.git("checkout", "-q", "-b", "f1")
        self.commit("f1.txt", "f1\n")
        self.git("checkout", "-q", "main")
        self.commit("f2.txt", "f2\n")
        self.git("merge", "-q", "--no-commit", "f1")
        (self.work / "evil.txt").write_text(f"tok={TOKEN}\n")
        self.git("add", "evil.txt")
        self.git("commit", "-q", "-m", "merge")
        self.assertNotEqual(self.push("main").returncode, 0)

    def test_a_new_branch_is_scanned_against_the_remote_it_goes_to(self):
        self.git("checkout", "-q", "-b", "feat")
        self.commit("s.txt", f"tok={TOKEN}\n")
        self.git("update-ref", "refs/remotes/other/feat", "HEAD")
        self.assertNotEqual(self.push("feat").returncode, 0)

    def test_a_history_rewrite_blocks(self):
        self.commit("b.txt", "b\n")
        self.push("main")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.commit("c.txt", "c\n")
        result = self.push("--force", "main")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("history rewrite", result.output)

    def test_a_clean_push_passes(self):
        self.git("checkout", "-q", "-b", "feat")
        self.commit("b.txt", "b\n")
        result = self.push("feat")
        self.assertEqual(result.returncode, 0, result.output)
        self.assertIn("All gates passed", result.output)
