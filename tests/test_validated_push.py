"""A push to main needs a passing full validation on record for the pushed tree."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _support import REPO_ROOT, git_env, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import validated  # noqa: E402

HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-push"
LAUNCHER = REPO_ROOT / "scripts" / "olivercode"
ZERO = "0" * 40


class ValidatedPush(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One remote and one work repo with the pre-push hook installed per class; each test copies them."""
        cls._template = Path(tempfile.mkdtemp(prefix="validated-template-")).resolve()
        cls.addClassCleanup(shutil.rmtree, cls._template, ignore_errors=True)
        env = git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        remote = scratch_repo(cls._template / "remote.git", bare=True)
        work = scratch_repo(cls._template / "work", branch="main", identity=False)
        (work / "scripts").mkdir()
        (work / "scripts" / "validate.sh").write_text("olivercode validated record\n")
        for args in (["add", "-A"], ["commit", "-q", "-m", "init"], ["remote", "add", "origin", str(remote)]):
            subprocess.run(["git", *args], cwd=work, env=env, capture_output=True, text=True)
        hook = work / ".git" / "hooks" / "pre-push"
        shutil.copy(HOOK, hook)
        hook.chmod(0o755)

    def setUp(self):
        self.tmp = temp_dir(self, "validated-")
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = git_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                           GIT_COMMITTER_EMAIL="t@example.com", OLIVERCODE_HOME=str(self.home),
                           OLIVERCODE_LAUNCHER=str(LAUNCHER))
        self.remote, self.work = self.tmp / "remote.git", self.tmp / "work"
        shutil.copytree(self._template / "remote.git", self.remote, symlinks=True)
        shutil.copytree(self._template / "work", self.work, symlinks=True)
        self.git("remote", "set-url", "origin", str(self.remote))

    def git(self, *args, env=None):
        return subprocess.run(["git", *args], cwd=self.work, env={**self.env, **(env or {})}, capture_output=True, text=True)

    def tree(self):
        return self.git("rev-parse", "HEAD^{tree}").stdout.strip()

    def write_record(self, tree, when=None, code=0):
        when = when or datetime.now(timezone.utc)
        line = json.dumps({"tree": tree, "time": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "exit": code})
        with open(self.home / "validated.jsonl", "a") as f:
            f.write(line + "\n")

    def push(self, ref="main", **env):
        result = self.git("push", "origin", ref, env=env)  # the extra settings last for this push only
        result.output = result.stdout + result.stderr
        return result

    def test_a_record_for_the_tree_allows_the_push(self):
        self.write_record(self.tree())
        result = self.push()
        self.assertEqual(result.returncode, 0, result.output)

    def test_no_record_refuses_with_the_how_to(self):
        result = self.push()
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("bash scripts/validate.sh", result.output)

    def test_a_record_for_another_tree_refuses(self):
        self.write_record("1" * 40)
        result = self.push()
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no passing full validation", result.output)

    def test_a_record_of_a_failed_validation_refuses(self):
        # Lesson S-no-validate: a push happens only after the repo's validation passes.
        self.write_record(self.tree(), code=1)
        result = self.push()
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("bash scripts/validate.sh", result.output)

    def test_a_record_older_than_seven_days_refuses(self):
        self.write_record(self.tree(), datetime.now(timezone.utc) - timedelta(days=8))
        result = self.push()
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no passing full validation", result.output)

    def test_a_non_main_push_needs_no_validation_record_once_the_branch_override_is_set(self):
        self.git("checkout", "-q", "-b", "feat")
        result = self.push("feat", ALLOW_BRANCH_PUSH="1")
        self.assertEqual(result.returncode, 0, result.output)

    def test_the_override_allows_with_one_stderr_line_and_a_log_entry(self):
        result = self.push(OLIVERCODE_ALLOW_UNVALIDATED_PUSH="1")
        self.assertEqual(result.returncode, 0, result.output)
        self.assertIn("OLIVERCODE_ALLOW_UNVALIDATED_PUSH", result.stderr)
        self.assertIn("unvalidated", (self.home / "failures.log").read_text())

    def test_the_override_log_entry_works_when_loaded_bare(self):
        code = ("import sys, validated; from pathlib import Path\n"
                "sys.exit(validated.check(Path(sys.argv[1]), sys.argv[2]))")
        sha = self.git("rev-parse", "HEAD").stdout.strip()
        env = {**self.env, "OLIVERCODE_ALLOW_UNVALIDATED_PUSH": "1", "PYTHONPATH": str(REPO_ROOT / "scripts" / "lib")}
        done = subprocess.run([sys.executable, "-c", code, str(self.work), sha], env=env, capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("unvalidated", (self.home / "failures.log").read_text())

    def test_a_repo_without_the_writer_skips(self):
        (self.work / "scripts" / "validate.sh").write_text("echo other\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "other")
        result = self.push()
        self.assertEqual(result.returncode, 0, result.output)
        self.assertIn("skipped", result.output)

    def test_the_launcher_recorded_by_a_pass_is_found(self):
        del self.env["OLIVERCODE_LAUNCHER"]
        (self.home / "launcher").write_text(str(LAUNCHER) + "\n")
        result = self.push()
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no passing full validation", result.output)
        self.assertNotIn("no olivercode launcher resolves", result.output)

    def oc_checkout(self):
        """A home whose ~/.claude/CLAUDE.md links into a checkout holding scripts/olivercode, as `olivercode land` finds it."""
        oc = self.tmp / "oc"
        (oc / "scripts").mkdir(parents=True)
        (oc / "CLAUDE.md").write_text("x\n")
        shutil.copy(LAUNCHER, oc / "scripts" / "olivercode")
        (self.tmp / "userhome" / ".claude").mkdir(parents=True)
        (self.tmp / "userhome" / ".claude" / "CLAUDE.md").symlink_to(oc / "CLAUDE.md")
        return self.tmp / "userhome"

    def test_a_plain_push_resolves_the_launcher_of_the_checkout_claude_md_links_to(self):
        del self.env["OLIVERCODE_LAUNCHER"]
        (self.home / "launcher").write_text(str(self.tmp / "gone-worktree" / "scripts" / "olivercode") + "\n")  # a recorded worktree that was removed
        result = self.push(HOME=str(self.oc_checkout()), PATH="/usr/bin:/bin")
        self.assertNotIn("no olivercode launcher resolves", result.output)
        self.assertIn("validated", result.output)

    def test_no_launcher_anywhere_still_fails_closed_and_names_the_fix(self):
        del self.env["OLIVERCODE_LAUNCHER"]
        (self.tmp / "emptyhome").mkdir()
        result = self.push(HOME=str(self.tmp / "emptyhome"), PATH="/usr/bin:/bin")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no olivercode launcher resolves", result.output)
        self.assertIn("ln -sf", result.output)

    def test_a_missing_launcher_refuses_with_the_fix(self):
        result = self.push(OLIVERCODE_LAUNCHER=str(self.tmp / "nope"), PATH="/usr/bin:/bin")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no olivercode launcher resolves", result.output)
        self.assertIn("OLIVERCODE_LAUNCHER", result.output)

    def test_gate_3_applies_to_a_default_branch_with_another_name(self):
        self.git("checkout", "-q", "-b", "trunk")
        self.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        result = self.push("trunk")
        self.assertNotEqual(result.returncode, 0, result.output)
        self.assertIn("no passing full validation", result.output)
        self.write_record(self.tree())
        self.assertEqual(self.push("trunk").returncode, 0)


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "validated-rec-")
        self.home = self.tmp / "home"
        self.old = os.environ.get("OLIVERCODE_HOME")
        os.environ["OLIVERCODE_HOME"] = str(self.home)
        self.addCleanup(self._restore)
        self.repo = scratch_repo(self.tmp / "repo", branch="main")
        (self.repo / "a.txt").write_text("a\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], env=git_env(), check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "a"], env=git_env(), check=True)

    def _restore(self):
        if self.old is None:
            os.environ.pop("OLIVERCODE_HOME", None)
        else:
            os.environ["OLIVERCODE_HOME"] = self.old

    def test_the_record_holds_the_tree_of_the_working_tree_and_keeps_200_lines(self):
        # The tree is the same for every record() in a batch, so it is hashed once per batch rather than
        # 205 times: each hash alone costs three subprocess calls (#1143).
        (self.repo / "dirty.txt").write_text("new\n")
        tree_a = validated.working_tree(self.repo)
        for _ in range(100):
            validated.record(self.repo, tree_a)
        (self.repo / "dirty.txt").write_text("newer\n")
        tree_b = validated.working_tree(self.repo)
        for _ in range(105):
            validated.record(self.repo, tree_b)
        lines = (self.home / "validated.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 200)
        # The first five old-tree lines were dropped and the newest line is last: dropping the wrong end changes these counts.
        trees = [json.loads(l)["tree"] for l in lines]
        self.assertEqual((trees.count(trees[0]), trees.count(trees[-1])), (95, 105))
        self.assertNotEqual(trees[0], trees[-1])
        self.assertTrue((self.home / "launcher").read_text().strip().endswith("scripts/olivercode"))
        tree = json.loads(lines[-1])["tree"]
        head_tree = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}"], env=git_env(),
                                   capture_output=True, text=True).stdout.strip()
        self.assertNotEqual(tree, head_tree)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], env=git_env(), check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "b"], env=git_env(), check=True)
        self.assertEqual(tree, subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}"], env=git_env(),
                                              capture_output=True, text=True).stdout.strip())

    def test_an_untracked_lessons_file_does_not_change_the_tree_but_other_untracked_files_do(self):
        base = validated.working_tree(self.repo)
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs" / "LESSONS.jsonl").write_text('{"a": 1}\n')
        self.assertEqual(validated.working_tree(self.repo), base)
        (self.repo / "other.txt").write_text("x\n")
        self.assertNotEqual(validated.working_tree(self.repo), base)

    def test_a_tracked_lessons_file_still_counts(self):
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs" / "LESSONS.jsonl").write_text("1\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], env=git_env(), check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "l"], env=git_env(), check=True)
        base = validated.working_tree(self.repo)
        (self.repo / "docs" / "LESSONS.jsonl").write_text("2\n")
        self.assertNotEqual(validated.working_tree(self.repo), base)

    def test_a_failing_validate_writes_nothing(self):
        (self.repo / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "validate.sh", self.repo / "scripts" / "validate.sh")
        # An unknown check-repo directory fails before the record step,.
        result = subprocess.run(["bash", str(self.repo / "scripts" / "validate.sh"), "--check-repo", str(self.tmp / "none")],
                                capture_output=True, text=True, env={**os.environ, "OLIVERCODE_HOME": str(self.home),
                                "OLIVERCODE_VALIDATE_SLOT": "none"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / "validated.jsonl").exists())

    def test_validate_sh_records_only_at_the_end_of_a_full_run(self):
        text = (REPO_ROOT / "scripts" / "validate.sh").read_text()
        self.assertEqual(text.count("validated record"), 1)
        self.assertIn("run_gates\n      python3 \"${SCRIPT_DIR}/olivercode\" validated record \"$tree\"\n      ;;", text)
        self.assertLess(text.index("validated snapshot"), text.index("run_build_hooks\n      run_gates"))

    def test_an_edit_during_a_run_leaves_the_stamp_on_the_tree_that_started(self):
        before = validated.working_tree(self.repo)
        (self.repo / "edit.txt").write_text("during the gates\n")
        validated.record(self.repo, before)
        stamped = json.loads((self.home / "validated.jsonl").read_text().splitlines()[-1])["tree"]
        self.assertEqual(stamped, before)
        self.assertNotEqual(stamped, validated.working_tree(self.repo))
        self.assertTrue(validated.is_validated(before))
        self.assertFalse(validated.is_validated(validated.working_tree(self.repo)))


if __name__ == "__main__":
    unittest.main()
