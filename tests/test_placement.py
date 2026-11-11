"""Tests for scripts/lib/placement.py, scripts/hooks/placement_guard.py and the place and clean commands."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import placement  # noqa: E402

GUARD = REPO_ROOT / "scripts" / "hooks" / "placement_guard.py"


def make_config(root, watch, allow=()):
    return placement.Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive",
                            watch=list(watch), allow=list(allow))


class TestFindings(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.root = base / "Repos"
        self.root.mkdir()
        self.other = base / "Developer"
        self.other.mkdir()
        self.cfg = make_config(self.root, [self.other])

    def test_a_clean_machine_reports_nothing(self):
        scratch_repo(self.root / "app")
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_repo_outside_the_root_is_reported_with_its_destination(self):
        scratch_repo(self.other / "stray")
        (found,) = placement.findings(self.cfg)
        self.assertEqual(("repo", self.other / "stray"), (found.kind, found.path))
        self.assertIn(str(self.root / "stray"), found.fix)

    def test_an_allowed_checkout_outside_the_root_passes(self):
        scratch_repo(self.other / "vault")
        self.cfg.allow = [self.other / "vault"]
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_backup_folder_in_the_root_is_reported(self):
        (self.root / "app-backup-1106").mkdir()
        (found,) = placement.findings(self.cfg)
        self.assertEqual("backup", found.kind)

    def test_the_archive_folder_is_the_home_for_backups(self):
        (self.root / "_archive" / "app-backup-1106").mkdir(parents=True)
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_worktree_outside_the_worktree_folder_is_reported(self):
        repo = scratch_repo(self.root / "app")
        git(repo, "commit", "--allow-empty", "-q", "-m", "x")
        git(repo, "worktree", "add", "-q", str(self.root / "app-wt"), "-b", "side")
        kinds = [(f.kind, f.path.name) for f in placement.findings(self.cfg)]
        self.assertIn(("worktree", "app-wt"), kinds)

    def test_a_worktree_in_the_worktree_folder_passes(self):
        repo = scratch_repo(self.root / "app")
        git(repo, "commit", "--allow-empty", "-q", "-m", "x")
        (self.root / "_worktrees").mkdir()
        git(repo, "worktree", "add", "-q", str(self.root / "_worktrees" / "app-wt"), "-b", "side")
        self.assertEqual([], placement.findings(self.cfg))


class TestClean(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.cfg = make_config(base / "Repos", [])
        self.repo = scratch_repo(self.cfg.root / "app", branch="main")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "x")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.cfg.worktrees.mkdir()

    def add(self, name):
        path = self.cfg.worktrees / name
        git(self.repo, "worktree", "add", "-q", str(path), "-b", name)
        return path

    def test_a_merged_clean_worktree_is_listed_and_kept_without_apply(self):
        path = self.add("done")
        self.assertIn(f"REMOVE {path}", " ".join(placement.clean(self.cfg)))
        self.assertTrue(path.exists())

    def test_apply_removes_a_merged_clean_worktree(self):
        path = self.add("done")
        placement.clean(self.cfg, apply=True)
        self.assertFalse(path.exists())

    def test_uncommitted_work_is_kept(self):
        path = self.add("busy")
        (path / "note.txt").write_text("work\n")
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith("KEEP") and "uncommitted" in line for line in lines))

    def test_unmerged_commits_are_kept(self):
        path = self.add("ahead")
        git(path, "commit", "--allow-empty", "-q", "-m", "more")
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith("KEEP") and "not on origin/main" in line for line in lines))


class TestViolation(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.cfg = make_config(base / "Repos", [])
        self.cfg.root.mkdir()
        self.cwd = self.cfg.root / "app"

    def check(self, line):
        return placement.violation(placement.split(line), self.cwd, self.cfg)

    def test_a_worktree_under_the_worktree_folder_is_allowed(self):
        self.assertEqual("", self.check(f"git worktree add {self.cfg.worktrees}/x -b x"))

    def test_a_worktree_elsewhere_is_refused_and_names_the_right_path(self):
        why = self.check("git worktree add /tmp/x -b x")
        self.assertIn(f"{self.cfg.worktrees}/x", why)

    def test_a_relative_worktree_beside_the_repo_is_refused(self):
        self.assertTrue(self.check("git worktree add ../app-wt main"))

    def test_a_clone_into_the_root_is_allowed(self):
        self.assertEqual("", self.check(f"git clone https://github.com/o/r.git {self.cfg.root}/r"))

    def test_a_clone_into_the_current_folder_outside_the_root_is_refused(self):
        self.cwd = self.cfg.root.parent / "Downloads"
        self.assertIn(f"{self.cfg.root}/r", self.check("git clone https://github.com/o/r.git"))

    def test_other_git_commands_are_ignored(self):
        self.assertEqual("", self.check("git worktree list"))
        self.assertEqual("", self.check("git status"))


class TestGuardScript(unittest.TestCase):
    def run_guard(self, command, cwd):
        payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
        done = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True)
        return done.returncode, done.stdout

    def test_an_unrelated_command_prints_nothing(self):
        self.assertEqual((0, ""), self.run_guard("ls -la", "/tmp"))

    def test_garbage_input_fails_open(self):
        done = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
        self.assertEqual((0, ""), (done.returncode, done.stdout))


if __name__ == "__main__":
    unittest.main()
