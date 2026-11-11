"""olivercode maintain repairs what is safe, reports what is not, and writes both to the logs."""

import contextlib
import io
import os
import plistlib
import unittest
from pathlib import Path
from unittest import mock

from _support import git, load_script, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, maintain, placement  # noqa: E402


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
