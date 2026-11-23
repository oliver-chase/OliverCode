"""olivercode maintain repairs what is safe, reports what is not, and writes both to the logs."""

import os
import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _maintain_case import Base
from _support import git, git_env, load_script, quiet, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, hygiene, maintain, placement  # noqa: E402


class TestRetiredJobs(Base):
    def test_a_job_for_a_removed_command_is_reported_and_removed_by_fix(self):
        agents = temp_dir(self)
        plist = agents / f"com.olivercode.{maintain.RETIRED_JOBS[0]}.plist"
        plist.write_text("x")
        with mock.patch.object(maintain.subprocess, "run"):
            self.assertEqual(["retiredjob"], [p.step for p in maintain.check_retired_jobs(False, agents)])
            self.assertTrue(plist.exists())
            self.assertTrue(maintain.check_retired_jobs(True, agents)[0].fixed)
        self.assertFalse(plist.exists())
        self.assertEqual([], maintain.check_retired_jobs(True, agents))


class TestHooksPath(Base):
    def repo(self):
        repo = scratch_repo(self.root / "app")
        (repo / ".githooks").mkdir()
        (repo / ".githooks" / "pre-commit").write_text("#!/bin/sh\n")
        (repo / ".githooks" / "pre-commit").chmod(0o755)
        return repo

    def test_an_absolute_hooks_path_is_reported_and_reset_by_fix(self):
        repo = self.repo()
        git(repo, "config", "core.hooksPath", str(repo / ".githooks"))
        found = maintain.check_hooks_path(self.cfg, fix=False)
        self.assertEqual(["hookspath"], [p.step for p in found])
        self.assertFalse(found[0].fixed)
        maintain.check_hooks_path(self.cfg, fix=True)
        self.assertEqual(".githooks", git(repo, "config", "--get", "core.hooksPath").stdout.strip())

    def test_the_relative_value_and_an_unset_path_report_nothing(self):
        repo = self.repo()
        self.assertEqual([], maintain.check_hooks_path(self.cfg, fix=True))
        git(repo, "config", "core.hooksPath", ".githooks")
        self.assertEqual([], maintain.check_hooks_path(self.cfg, fix=True))


class TestLinks(Base):
    def test_a_dangling_link_is_repaired_by_install(self):
        (self.claude / "CLAUDE.md").symlink_to(self.claude / "gone.md")
        good = self.claude / "good.md"
        good.write_text("x")
        installed = []
        def install():
            (self.claude / "CLAUDE.md").unlink()
            (self.claude / "CLAUDE.md").symlink_to(good)
            installed.append(1)
        problems = maintain.check_links(True, install=install)
        self.assertTrue(problems[0].fixed)
        self.assertEqual(installed, [1])

    def test_without_fix_nothing_changes(self):
        (self.claude / "CLAUDE.md").symlink_to(self.claude / "gone.md")
        problems = maintain.check_links(False, install=lambda: self.fail("must not install"))
        self.assertFalse(problems[0].fixed)
        self.assertTrue(problems[0].fixable)

    def test_sound_links_report_nothing(self):
        self.assertEqual(maintain.check_links(True), [])


class TestWorktrees(Base):
    def make(self):
        repo = self.root / "app"
        scratch_repo(repo)
        (repo / "a.txt").write_text("a")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "x")
        wt = temp_dir(self) / "wt"
        git(repo, "worktree", "add", "-q", "-b", "side", str(wt))
        import shutil
        shutil.rmtree(wt)
        return repo

    def test_a_worktree_with_no_folder_is_pruned(self):
        repo = self.make()
        found = maintain.check_worktrees(self.cfg, True)
        self.assertTrue(found[0].fixed)
        self.assertEqual(maintain.check_worktrees(self.cfg, False), [])
        self.assertTrue(repo.exists())

    def test_checking_only_leaves_the_metadata(self):
        self.make()
        self.assertFalse(maintain.check_worktrees(self.cfg, False)[0].fixed)
        self.assertEqual(len(maintain.check_worktrees(self.cfg, False)), 1)


class TestBranches(Base):
    def make(self):
        repo = self.root / "app"
        scratch_repo(repo)
        (repo / "a.txt").write_text("a")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "x")
        git(repo, "branch", "-M", "main")
        git(repo, "branch", "done")  # at main's tip, so merged
        git(repo, "checkout", "-q", "-b", "old")
        (repo / "b.txt").write_text("b")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "y")
        git(repo, "checkout", "-q", "main")
        return repo

    def test_a_merged_branch_is_listed_and_deleted_with_fix_and_an_unmerged_young_one_is_left(self):
        repo = self.make()
        found = maintain.check_branches(self.cfg, False)
        self.assertEqual(["branches"], [p.step for p in found])
        self.assertIn("done", found[0].text)
        self.assertTrue(found[0].fixable)
        fixed = maintain.check_branches(self.cfg, True)
        self.assertTrue(fixed[0].fixed)
        branches = git(repo, "branch", "--format=%(refname:short)").stdout.split()
        self.assertEqual(["main", "old"], sorted(branches))

    def test_an_unmerged_branch_older_than_a_day_with_no_worktree_is_reported_and_never_deleted(self):
        repo = self.make()
        git(repo, "branch", "-d", "done")
        import time
        found = maintain.check_branches(self.cfg, True, now=time.time() + 25 * 3600)
        self.assertEqual(1, len(found))
        self.assertIn("old", found[0].text)
        self.assertFalse(found[0].fixable)
        self.assertIn("old", git(repo, "branch", "--format=%(refname:short)").stdout.split())

    def test_a_branch_a_worktree_has_checked_out_is_left_alone(self):
        repo = self.make()
        git(repo, "worktree", "add", "-q", str(temp_dir(self) / "wt"), "done")
        import time
        self.assertEqual([p for p in maintain.check_branches(self.cfg, True, now=time.time() + 25 * 3600) if "done" in p.text], [])
        self.assertIn("done", git(repo, "branch", "--format=%(refname:short)").stdout.split())


class TestIcloud(Base):
    def test_evicted_git_files_are_downloaded(self):
        repo = self.root / "app"
        scratch_repo(repo)
        state = {"left": [repo / ".git" / "HEAD"]}
        def fake_dataless(_repo):
            return list(state["left"])
        def fake_download(paths, seconds=0):
            state["left"] = []
            return len(paths)
        with mock.patch.object(maintain, "dataless_files", fake_dataless), mock.patch.object(maintain.hygiene, "download", fake_download):
            self.assertTrue(maintain.check_icloud(self.cfg, True)[0].fixed)


class TestCopies(Base):
    def make(self):
        repo = self.root / "app"
        scratch_repo(repo)
        (repo / "a.txt").write_text("a")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "x")
        return repo

    def test_identical_copy_is_deleted_and_older_copy_is_archived(self):
        repo = self.make()
        (repo / "a 2.txt").write_text("a")
        (repo / "b.txt").write_text("new"); (repo / "b 2.txt").write_text("old")
        os.utime(repo / "b 2.txt", (1, 1))
        found = maintain.check_copies(self.cfg, True)
        self.assertTrue(found[0].fixed)
        self.assertFalse((repo / "a 2.txt").exists())
        self.assertEqual((self.cfg.archive / "stray-copies" / "app" / "b 2.txt").read_text(), "old")

    def test_a_newer_differing_copy_is_kept_for_the_owner(self):
        repo = self.make()
        (repo / "a 2.txt").write_text("changed")
        os.utime(repo / "a.txt", (1, 1))
        found = maintain.check_copies(self.cfg, True)
        self.assertFalse(found[0].fixed)
        self.assertEqual((repo / "a 2.txt").read_text(), "changed")

    def test_checking_only_deletes_nothing_and_a_clean_repo_reports_nothing(self):
        repo = self.make()
        self.assertEqual(maintain.check_copies(self.cfg, False), [])
        (repo / "a 2.txt").write_text("a")
        self.assertTrue(maintain.check_copies(self.cfg, False)[0].fixable)
        self.assertTrue((repo / "a 2.txt").exists())

    def test_an_evicted_copy_is_never_read_and_stays(self):
        repo = self.make()
        (repo / "a 2.txt").write_text("a")
        with mock.patch.object(hygiene, "evicted", return_value=True):
            found = maintain.check_copies(self.cfg, True)
        self.assertFalse(found[0].fixed)
        self.assertTrue((repo / "a 2.txt").exists())

    def test_an_evicted_pair_is_downloaded_then_compared_and_a_dry_run_downloads_nothing(self):
        repo = self.make()
        (repo / "a 2.txt").write_text("a")
        state = {"evicted": True}
        fetched = []
        def fake_fetch(paths):
            fetched.extend(paths)
            state["evicted"] = False
        with mock.patch.object(hygiene, "evicted", side_effect=lambda p: state["evicted"]), \
                mock.patch.object(hygiene, "download", fake_fetch):
            self.assertEqual("newer", hygiene.stray_copies(repo)[0].verdict)  # no fetch given: left alone
            self.assertEqual([], fetched)
            problem = maintain.check_copies(self.cfg, True)[0]
        self.assertTrue(problem.fixed)
        self.assertEqual(2, len(fetched))
        self.assertFalse((repo / "a 2.txt").exists())

    def test_a_file_that_stays_evicted_after_the_download_is_kept(self):
        repo = self.make()
        (repo / "a 2.txt").write_text("a")
        with mock.patch.object(hygiene, "evicted", return_value=True), mock.patch.object(hygiene, "download", lambda paths: None):
            problem = maintain.check_copies(self.cfg, True)[0]
        self.assertFalse(problem.fixed)
        self.assertTrue((repo / "a 2.txt").exists())

    def test_a_name_with_a_number_and_no_original_is_not_a_copy(self):
        repo = self.make()
        (repo / "Chapter 2.txt").write_text("x")
        self.assertEqual(maintain.check_copies(self.cfg, False), [])


if __name__ == "__main__":
    unittest.main()
