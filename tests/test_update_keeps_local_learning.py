"""Story #661: update keeps each device's skill overrides and lessons, and refuses a checkout it cannot pull into."""

import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git_env, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_fleet, cmd_install, lessons  # noqa: E402

ENV = {**git_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], env=ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


def write(root, rel, text):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


class Checkout(unittest.TestCase):
    """An origin with one shipped skill, this device's clone of it, and an isolated home."""

    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.origin, self.seed, self.clone = base / "origin.git", base / "seed", base / "checkout"
        git(base, "init", "--bare", "-q", "-b", "main", str(self.origin))
        git(base, "init", "-q", "-b", "main", str(self.seed))
        write(self.seed, "skills/shipped/SKILL.md", "shipped v1")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", "seed (#661)")
        git(self.seed, "remote", "add", "origin", str(self.origin))
        git(self.seed, "push", "-q", "-u", "origin", "main")
        git(base, "clone", "-q", str(self.origin), str(self.clone))
        self.home, self.ohome = temp_dir(self, resolve=True), temp_dir(self, resolve=True)
        for patch in (mock.patch.dict(os.environ, {"HOME": str(self.home), "OLIVERCODE_HOME": str(self.ohome)}),
                      mock.patch("lib.repo_gates.hook_templates"),
                      mock.patch("lib.repo_gates.has_gates", return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)

    def release(self, rel, text):
        """Push a new shipped commit to origin, as a release does."""
        write(self.seed, rel, text)
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", "release (#661)")
        git(self.seed, "push", "-q", "origin", "main")

    def install(self):
        return quiet(cmd_install.command_install, self.clone)

    def update(self):
        """Run `olivercode update` on the clone: git runs for real, install runs in-process, sync-hooks is a no-op."""
        calls, real_run = [], subprocess.run

        def fake_run(argv, **kwargs):
            if argv[0] == "git":
                return real_run(argv, **kwargs)
            calls.append(argv[-1])
            if argv[-1] == "install":
                cmd_install.command_install(self.clone)
            return mock.Mock(returncode=0)
        with mock.patch.object(cmd_fleet.subprocess, "run", side_effect=fake_run):
            code, out = quiet(cmd_fleet.command_update, self.clone)
        return code, calls, out


class ScenarioOneKeepsLocalLearning(Checkout):
    def test_shipped_files_change_while_the_override_and_lessons_stay(self):
        write(self.ohome / "skills", "shipped/SKILL.md", "local override")
        lessons.add("a check missed", "the skill drifted", "check the override", repo=self.clone)
        lesson_file = lessons.path(self.clone)
        lesson_before = lesson_file.read_bytes()
        self.release("skills/shipped/SKILL.md", "shipped v2")

        code, calls, _ = self.update()

        self.assertEqual((code, calls), (0, ["install", "sync-hooks", "conform"]))
        self.assertEqual((self.clone / "skills" / "shipped" / "SKILL.md").read_text(), "shipped v2")
        link = self.home / ".claude" / "skills" / "shipped"
        self.assertEqual(link.resolve(), (self.ohome / "skills" / "shipped").resolve())
        self.assertEqual((link / "SKILL.md").read_text(), "local override")
        self.assertEqual(lesson_file.read_bytes(), lesson_before)
        self.assertEqual(len(lessons.read(self.clone)), 1)
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")

    def test_an_override_only_skill_is_linked_too(self):
        write(self.ohome / "skills", "my-own/SKILL.md", "this device only")
        self.install()
        self.assertEqual((self.home / ".claude" / "skills" / "my-own" / "SKILL.md").read_text(), "this device only")

    def test_a_removed_override_points_the_skill_back_at_the_shipped_copy_in_place(self):
        write(self.ohome / "skills", "shipped/SKILL.md", "local override")
        self.install()
        shutil.rmtree(self.ohome / "skills" / "shipped")
        _, out = self.install()
        link = self.home / ".claude" / "skills" / "shipped"
        self.assertEqual(link.resolve(), (self.clone / "skills" / "shipped").resolve())
        self.assertFalse(any(p.name.endswith("pre-olivercode") for p in (self.home / ".claude" / "skills").iterdir()), out)


class ScenarioTwoRefusesADirtyOrDivergedCheckout(Checkout):
    def refused(self, head, out_and_codes):
        """Assert update changed nothing and printed one `Fix:` line; return that line."""
        code, calls, out = out_and_codes
        self.assertEqual((code, calls), (1, []), out)
        self.assertIn("changed nothing", out)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), head)
        fixes = [line for line in out.splitlines() if line.startswith("Fix: git -C ")]
        self.assertEqual(len(fixes), 1, out)
        return fixes[0]

    def test_a_changed_tracked_file_is_refused_and_the_stash_command_is_named(self):
        self.release("skills/shipped/SKILL.md", "shipped v2")
        write(self.clone, "skills/shipped/SKILL.md", "mine")
        fix = self.refused(git(self.clone, "rev-parse", "HEAD"), self.update())
        self.assertIn("stash push", fix)
        self.assertEqual((self.clone / "skills" / "shipped" / "SKILL.md").read_text(), "mine")

    def test_a_rebase_in_progress_is_refused_and_the_abort_command_is_named(self):
        self.release("skills/shipped/SKILL.md", "shipped v2")
        (self.clone / ".git" / "rebase-merge").mkdir()
        self.assertIn("rebase --abort", self.refused(git(self.clone, "rev-parse", "HEAD"), self.update()))

    def test_commits_origin_lacks_are_refused_even_with_nothing_to_pull_and_the_branch_fix_is_named(self):
        """An installed checkout that holds commits origin lacks is refused, so none of its commits is left on main (#785)."""
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "local work (#661)")
        fix = self.refused(git(self.clone, "rev-parse", "HEAD"), self.update())
        self.assertIn("branch olivercode-local", fix)
        self.assertIn("reset --keep origin/main", fix)
        self.assertNotIn("push", fix)

    def test_a_diverged_checkout_is_refused_and_a_fix_with_no_push_is_named(self):
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "local work (#661)")
        self.release("skills/shipped/SKILL.md", "shipped v2")
        fix = self.refused(git(self.clone, "rev-parse", "HEAD"), self.update())
        self.assertIn("branch olivercode-local", fix)
        self.assertNotIn("push", fix)


if __name__ == "__main__":
    unittest.main()
