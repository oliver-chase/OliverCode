"""olivercode maintain repairs what is safe, reports what is not, and writes both to the logs."""

import contextlib
import io
import os
import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import git, git_env, load_script, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, hygiene, maintain, placement  # noqa: E402


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class Base(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.root = temp_dir(self)
        self.claude = temp_dir(self)
        for target, value in (
            (os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log")}),
        ):
            p = mock.patch.dict(target, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(maintain, "claude_dir", return_value=self.claude); p.start(); self.addCleanup(p.stop)
        self.cfg = placement.Config(root=self.root, worktrees=self.root / "_worktrees", archive=self.root / "_archive", watch=[], allow=[])


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
        with mock.patch.object(maintain, "dataless_files", fake_dataless), mock.patch.object(maintain, "download", fake_download):
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

    def test_a_name_with_a_number_and_no_original_is_not_a_copy(self):
        repo = self.make()
        (repo / "Chapter 2.txt").write_text("x")
        self.assertEqual(maintain.check_copies(self.cfg, False), [])


class TestSyncedRoot(Base):
    def synced(self):
        root = self.root / "Dropbox" / "Repos"
        root.mkdir(parents=True)
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

    def test_documents_is_synced_when_icloud_mirrors_it(self):
        home = temp_dir(self, resolve=True)
        root = home / "Documents" / "Repos"; root.mkdir(parents=True)
        self.assertEqual(hygiene.synced_marker(root, home), "")
        (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents").mkdir(parents=True)
        self.assertEqual(hygiene.synced_marker(root, home), "iCloud Desktop & Documents")


class TestStaleDocs(Base):
    def commit(self, repo, when, *paths):
        git(repo, "add", *paths)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], env=git_env(GIT_COMMITTER_DATE=when), check=True, capture_output=True)

    def test_a_doc_that_trails_the_file_it_names_is_flagged_and_a_fresh_one_is_not(self):
        repo = self.root / "app"
        scratch_repo(repo)
        (repo / "docs").mkdir()
        (repo / "docs" / "A.md").write_text("See `run.sh`.")
        (repo / "docs" / "B.md").write_text("See `run.sh`.")
        (repo / "run.sh").write_text("1")
        self.commit(repo, "2026-01-01T00:00:00", "docs/A.md", "run.sh")
        (repo / "run.sh").write_text("2")
        self.commit(repo, "2026-06-01T00:00:00", "run.sh", "docs/B.md")
        found = hygiene.stale_docs(repo)
        self.assertEqual(len(found), 1)
        self.assertIn("docs/A.md names run.sh", found[0])


class TestReport(Base):
    def test_an_unfixable_problem_is_logged_and_the_exit_code_is_one(self):
        problems = [maintain.Problem("placement", "repo out of place: /x. move it")]
        self.assertEqual(quiet(maintain.report, problems, True), 1)
        self.assertEqual(failure_log.entries()[0][2], "maintain")
        self.assertIn("NEEDS A DECISION", (self.home / "maintenance.log").read_text())

    def test_everything_fixed_exits_zero_and_logs_no_failure(self):
        self.assertEqual(quiet(maintain.report, [maintain.Problem("links", "x", True, True)], True), 0)
        self.assertEqual(failure_log.entries(), [])

    def test_usage_error_exits_one(self):
        self.assertEqual(quiet(maintain.command_maintain, ["--bogus"]), 1)


class TestSchedule(Base):
    def test_the_job_runs_maintain_fix_daily(self):
        job = maintain.plist()
        self.assertEqual(job["ProgramArguments"][-2:], ["maintain", "--fix"])
        self.assertIn("StartCalendarInterval", job)
        plistlib.loads(plistlib.dumps(job))


if __name__ == "__main__":
    unittest.main()
