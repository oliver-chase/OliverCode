"""olivercode maintain: slow repos and the synced roots."""

import subprocess
import unittest
from unittest import mock

from _maintain_case import Base
from _support import git, quiet, scratch_repo, temp_dir
from lib import hygiene, maintain, placement


class TestSlowRepo(Base):
    def test_a_git_call_that_times_out_skips_the_repo_and_does_not_stop_the_run(self):
        scratch_repo(self.root / "app")
        slow = subprocess.TimeoutExpired(["git"], 60)
        with mock.patch.object(hygiene.subprocess, "run", side_effect=slow):
            self.assertEqual([], hygiene.stray_copies(self.root / "app"))
            self.assertEqual([], maintain.check_copies(self.cfg, True))


class TestSyncedRoot(Base):
    def synced(self):
        root = self.root / "Dropbox" / "Repos"
        root.mkdir(parents=True)
        p = mock.patch("pathlib.Path.home", return_value=self.root); p.start(); self.addCleanup(p.stop)
        repo = root / "app"
        scratch_repo(repo)
        (repo / "a.txt").write_text("a")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "x")
        cfg = placement.Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive", watch=[], allow=[])
        return repo, cfg

    def test_git_moves_out_of_the_sync_and_still_works(self):
        repo, cfg = self.synced()
        self.assertTrue(maintain.check_git_sync(cfg, False)[0].fixable)
        self.assertFalse((repo / ".git").is_symlink())
        self.assertTrue(maintain.check_git_sync(cfg, True)[0].fixed)
        self.assertTrue((repo / ".git").is_symlink())
        self.assertTrue((repo / ".git.nosync" / "HEAD").exists())
        self.assertEqual(git(repo, "log", "--oneline").stdout.count("\n"), 1)
        self.assertEqual(maintain.check_git_sync(cfg, True), [])

    def test_the_git_folder_is_ignored_even_for_a_repo_protected_before_the_rule_existed(self):
        repo, cfg = self.synced()
        maintain.check_git_sync(cfg, True)
        self.assertNotIn(".git.nosync", git(repo, "status", "--short").stdout)
        self.assertEqual(placement.linked_worktrees(cfg), [])  # the main checkout is not a stray worktree
        (repo / ".git.nosync" / "info" / "exclude").write_text("")
        self.assertTrue(maintain.check_git_sync(cfg, True)[0].fixed)
        self.assertNotIn(".git.nosync", git(repo, "status", "--short").stdout)

    def test_a_link_the_sync_renamed_is_restored(self):
        repo, cfg = self.synced()
        maintain.check_git_sync(cfg, True)
        (repo / ".git").rename(repo / ".git 2")
        self.assertTrue(maintain.check_git_sync(cfg, False)[0].fixable)
        self.assertTrue(maintain.check_git_sync(cfg, True)[0].fixed)
        self.assertTrue((repo / ".git").is_symlink())
        self.assertFalse((repo / ".git 2").exists() or (repo / ".git 2").is_symlink())
        self.assertEqual(git(repo, "log", "--oneline").stdout.count("\n"), 1)

    def test_stray_git_folders_are_removed_or_archived_and_an_object_store_is_kept(self):
        repo, cfg = self.synced()
        maintain.check_git_sync(cfg, True)
        (repo / ".git 2").mkdir()
        (repo / ".git 3").mkdir()
        (repo / ".git 3" / "index 7").write_text("old index")
        (repo / ".git 4" / "objects").mkdir(parents=True)
        self.assertTrue(maintain.check_git_sync(cfg, False)[0].fixable)
        maintain.check_git_sync(cfg, True)
        self.assertFalse((repo / ".git 2").exists())
        self.assertFalse((repo / ".git 3").exists())
        self.assertEqual("old index", (cfg.archive / "stray-copies" / "app" / ".git 3" / "index 7").read_text())
        self.assertTrue((repo / ".git 4" / "objects").is_dir())
        self.assertEqual(1, git(repo, "log", "--oneline").stdout.count("\n"))

    def test_a_running_git_operation_leaves_the_repo_alone(self):
        repo, cfg = self.synced()
        (repo / ".git" / "index.lock").write_text("")
        problem = maintain.check_git_sync(cfg, True)[0]
        self.assertFalse(problem.fixed)
        self.assertIn("running", problem.text)
        self.assertTrue((repo / ".git").is_dir() and not (repo / ".git").is_symlink())

    def test_a_plain_root_reports_nothing(self):
        scratch_repo(self.root / "app")
        self.assertEqual(maintain.check_git_sync(self.cfg, True), [])
        self.assertFalse((self.root / "app" / ".git").is_symlink())


class TestSynced(Base):
    """On 2026-11-12 iCloud evicted every repo in ~/Documents/Repos and the posting jobs failed with "Resource deadlock avoided"."""

    def setUp(self):
        super().setUp()
        self.home = temp_dir(self, resolve=True)
        p = mock.patch.object(placement, "has_file_provider_xattr", return_value=False); p.start(); self.addCleanup(p.stop)

    def cfg_at(self, root):
        root.mkdir(parents=True, exist_ok=True)
        return placement.Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive", watch=[], allow=[])

    def test_every_synced_place_flags_repo_root_with_the_move(self):
        for place in placement.SYNCED_PLACES:
            with self.subTest(place=place):
                problems = maintain.check_synced(self.cfg_at(self.home / place / "Repos"), fleet=[], home=self.home)
                self.assertEqual([p.step for p in problems], ["synced"])
                self.assertIn(f"~/{place}", problems[0].text)
                self.assertIn("~/Developer/Repos", problems[0].text)
                self.assertFalse(problems[0].fixable)

    def test_a_fleet_repo_in_documents_is_flagged_and_a_safe_one_is_not(self):
        cfg = self.cfg_at(self.home / "Developer" / "Repos")
        stray = self.home / "Documents" / "notes"; stray.mkdir(parents=True)
        safe = cfg.root / "app"; safe.mkdir()
        problems = maintain.check_synced(cfg, fleet=[stray, safe], home=self.home)
        self.assertEqual(len(problems), 1)
        self.assertIn("notes", problems[0].text)
        self.assertIn("~/Developer/Repos/notes", problems[0].text)

    def test_a_file_provider_folder_is_synced_wherever_it_sits(self):
        root = self.home / "Elsewhere" / "Repos"
        placement.has_file_provider_xattr.side_effect = lambda path: path == root.parent
        self.assertEqual(placement.synced_place(root, self.home), str(root.parent))

    def test_a_safe_root_reports_nothing_and_maintain_exits_one_on_a_synced_root(self):
        self.assertEqual(maintain.check_synced(self.cfg_at(self.home / "Developer" / "Repos"), fleet=[], home=self.home), [])
        cfg = self.cfg_at(self.home / "Documents" / "Repos")
        with mock.patch("pathlib.Path.home", return_value=self.home):
            problems = maintain.run(False, cfg, health=False)
        self.assertIn("synced", [p.step for p in problems])
        self.assertEqual(quiet(maintain.report, problems, False)[0], 1)


if __name__ == "__main__":
    unittest.main()
