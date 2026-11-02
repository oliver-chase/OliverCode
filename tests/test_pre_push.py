"""The pre-push hook blocks a history rewrite and a secret in any commit the push sends."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git_env, scratch_repo

HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-push"
# Built at runtime so this file never holds a value the secret gates would match.
TOKEN = "ghp_" + "a" * 36


class PrePush(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One remote and one clone, built once and copied for each test."""
        cls._template = Path(tempfile.mkdtemp(prefix="pre-push-template-"))
        cls.env = git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                          GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        remote = scratch_repo(cls._template / "remote.git", bare=True)
        work = scratch_repo(cls._template / "work", branch="main", identity=False)
        (work / "a.txt").write_text("a\n")
        for args in (("add", "a.txt"), ("commit", "-q", "-m", "a.txt"),
                     ("remote", "add", "origin", str(remote)), ("push", "-q", "origin", "main")):
            subprocess.run(["git", *args], cwd=work, env=cls.env, check=True, capture_output=True)
        hook = work / ".git" / "hooks" / "pre-push"
        shutil.copy(HOOK, hook)
        hook.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._template, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pre-push-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
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

    def test_a_force_push_over_a_remote_commit_this_clone_lacks_still_scans(self):
        self.commit("s.txt", f"tok={TOKEN}\n")
        local = self.git("rev-parse", "HEAD").stdout.strip()
        unknown = "1" * 40
        hook = self.work / ".git" / "hooks" / "pre-push"
        result = subprocess.run([str(hook), "origin", str(self.remote)], cwd=self.work, env={**self.env, "ALLOW_FORCE_PUSH": "1"},
                                input=f"refs/heads/main {local} refs/heads/main {unknown}\n", capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)

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


if __name__ == "__main__":
    unittest.main()
