"""olivercode maintain repairs what is safe, reports what is not, and writes both to the logs."""

import contextlib
import fcntl
import io
import json
import os
import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _maintain_case import Base
from _support import REPO_ROOT, git, git_env, load_script, quiet, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, health_checks, hygiene, maintain, placement  # noqa: E402


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


SUITE_PASS = "  Ran 40 tests across 3 modules, all passed\nrun-tests: tests passed on commit abc123\n"
SUITE_FAIL = ("--- test_maintain ---\nRan 9 tests in 2.0s\nFAILED (failures=2)\n"
              "--- test_policy ---\nRan 12 tests in 1.0s\nFAILED (failures=1)\n"
              "  Ran 40 tests across 3 modules, 2 failed: test_maintain, test_policy\n"
              "=== validate: python smoke tests FAILED ===\nrun-tests: tests FAILED on commit abc123\n")


class TestCleanCloneSuite(unittest.TestCase):
    """The daily job runs the clean-clone suite once and records it; health fails a failed or stale record and names its modules (#977)."""

    def setUp(self):
        self.record = temp_dir(self) / "clean-clone-suite.json"

    def test_a_green_run_records_its_commit_exit_code_and_test_count(self):
        self.assertEqual({"commit": "abc123", "exit": 0, "tests": 40, "failed": []}, {k: v for k, v in maintain.suite_record(0, SUITE_PASS).items() if k != "at"})

    def test_a_failed_run_records_the_failing_modules(self):
        record = maintain.suite_record(1, SUITE_FAIL)
        self.assertEqual((1, 40, ["test_maintain", "test_policy"]), (record["exit"], record["tests"], record["failed"]))

    def test_the_daily_run_runs_the_suite_once_and_writes_the_record(self):
        with mock.patch.object(maintain, "run_clean_clone_suite", return_value=maintain.suite_record(0, SUITE_PASS)) as run:
            self.assertEqual([], maintain.check_suite(True, record=self.record))
        run.assert_called_once()
        self.assertEqual(0, json.loads(self.record.read_text())["exit"])

    def test_a_check_only_run_runs_no_suite(self):
        with mock.patch.object(maintain, "run_clean_clone_suite") as run:
            self.assertEqual([], maintain.check_suite(False, record=self.record))
        run.assert_not_called()
        self.assertFalse(self.record.exists())

    def test_a_failed_daily_run_is_a_problem_that_names_the_modules(self):
        with mock.patch.object(maintain, "run_clean_clone_suite", return_value=maintain.suite_record(1, SUITE_FAIL)):
            problems = maintain.check_suite(True, record=self.record)
        self.assertEqual(["suite"], [p.step for p in problems])
        self.assertIn("test_maintain, test_policy", problems[0].text)

    def test_health_fails_a_recorded_failure_and_names_its_modules(self):
        self.record.write_text(json.dumps(maintain.suite_record(1, SUITE_FAIL)))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = health_checks._check_clean_clone_suite(self.record, head="")
        self.assertEqual((0, 1, 0), result)
        self.assertIn("[FAIL]", out.getvalue())
        self.assertIn("test_maintain, test_policy", out.getvalue())

    def test_health_fails_a_record_older_than_two_days(self):
        record = maintain.suite_record(0, SUITE_PASS)
        record["at"] -= 3 * 86400
        self.record.write_text(json.dumps(record))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = health_checks._check_clean_clone_suite(self.record, head="")
        self.assertEqual((0, 1, 0), result)
        self.assertIn("3.0 days ago", out.getvalue())

    def test_health_does_not_count_a_record_for_another_commit(self):
        self.record.write_text(json.dumps({**maintain.suite_record(1, SUITE_FAIL), "commit": "a" * 40}))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = health_checks._check_clean_clone_suite(self.record, head="b" * 40)
        self.assertEqual((0, 0, 1), result)
        self.assertIn("[INFO]", out.getvalue())
        self.assertIn("aaaaaaaa", out.getvalue())

    def test_health_passes_a_fresh_green_record(self):
        self.record.write_text(json.dumps(maintain.suite_record(0, SUITE_PASS)))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual((1, 0, 0), health_checks._check_clean_clone_suite(self.record, head=""))


class TestFailureGaps(unittest.TestCase):
    """A failing check is reported and never becomes a candidate, a story or an issue (#978, #1275)."""

    def setUp(self):
        self.home = temp_dir(self)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_nightly_run_reports_each_failing_check_and_check_only_reports_none(self):
        gaps = [("acme/widget", "Rebase widget", "Fix: x"), ("acme/gadget", "Gate for task nightly", "Fix: y")]
        with mock.patch.object(maintain, "failure_gaps", return_value=gaps):
            found = maintain.check_failure_gaps(True)
            self.assertEqual([], maintain.check_failure_gaps(False))
        self.assertEqual(2, len(found))
        self.assertIn("acme/widget: Rebase widget", found[0].text)
        self.assertFalse(any(p.fixable for p in found))

    def test_a_stale_worktree_names_its_own_repo_and_a_task_names_the_engine(self):
        repo = scratch_repo(temp_dir(self) / "widget")
        git(repo, "remote", "add", "origin", "git@github.com:acme/widget.git")
        wt = mock.Mock(path=repo)
        with mock.patch.object(maintain.placement, "worktrees", return_value=[wt]), \
                mock.patch("lib.health_checks.stale_hook", return_value="hooks.py changed on origin/main"), \
                mock.patch("lib.schedules.ungated", return_value=[("nightly", 1.0)]), \
                mock.patch("lib.schedules.task_crons", return_value={}):
            gaps = maintain.failure_gaps()
        self.assertEqual(["acme/widget"], [g[0] for g in gaps if g[1].startswith("Rebase")])
        self.assertEqual([maintain.engine_slug()], [g[0] for g in gaps if g[1].startswith("Gate command")])

    def test_the_same_gate_failure_three_times_is_reported_and_no_candidate_is_written(self):
        """#1275: three identical failures, then the nightly run: the repeat is reported and nothing is filed or listed."""
        from lib import failure_log
        for _ in range(3):
            failure_log.record("gate 4", "land interrupted", "r")
        with mock.patch("subprocess.run") as gh, mock.patch.object(maintain, "failure_gaps", return_value=[]):
            problems = maintain.check_failure_gaps(True)
        self.assertTrue(any("gate 4: land interrupted blocked 3 times, latest" in p.text for p in problems))
        gh.assert_not_called()
        self.assertEqual([], sorted(p.name for p in self.home.iterdir() if "candidate" in p.name or "outbox" in p.name))
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "candidates.py").exists())
        self.assertFalse(hasattr(maintain, "file_failure_candidates"))


class TestStateFolder(Base):
    LIMITS = {"stateEntries": 80, "stateBytes": 52428800, "stateLogBytes": 100}

    def lock_held_by_a_live_process(self, name):
        """Hold a lock with flock on an open handle, as a live process does, and return the handle to close."""
        path = self.home / name
        path.touch()
        handle = path.open("rb")
        fcntl.flock(handle, fcntl.LOCK_EX)
        self.addCleanup(handle.close)
        return path

    def test_a_lock_no_process_holds_is_removed_and_a_held_one_stays(self):
        stale = self.home / "board-my-shop-1.lock"
        stale.touch()
        held = self.lock_held_by_a_live_process("board-my-shop-2.lock")
        found = maintain.check_state(False, self.home, self.LIMITS)
        self.assertEqual(["state"], [p.step for p in found])
        self.assertIn("1 lock file(s)", found[0].text)
        self.assertTrue(stale.exists())
        found = maintain.check_state(True, self.home, self.LIMITS)
        self.assertTrue(found[0].fixed)
        self.assertFalse(stale.exists())
        self.assertTrue(held.exists())

    def test_output_of_a_removed_job_is_removed_and_a_live_output_stays(self):
        dead = [self.home / "idle-sessions.out", self.home / "burndown.json", self.home / "work-map-state.json"]
        for path in dead:
            path.write_text("x")
        live = self.home / "maintain.out"
        live.write_text("x")
        self.assertFalse(maintain.check_state(False, self.home, self.LIMITS)[0].fixed)
        self.assertTrue(all(p.exists() for p in dead))
        found = maintain.check_state(True, self.home, self.LIMITS)
        self.assertIn("3 output file(s) of removed jobs", found[0].text)
        self.assertTrue(found[0].fixed)
        self.assertFalse(any(p.exists() for p in dead))
        self.assertTrue(live.exists())

    def test_a_log_over_its_limit_is_cut_to_its_newest_whole_lines(self):
        log = self.home / "maintenance.log"
        lines = [f"line {n:03d}\n" for n in range(40)]  # 9 bytes each, so 11 whole lines fit in 100 bytes
        log.write_text("".join(lines))
        os.utime(log, (1, 1))  # quiet for a long time, so a run may cut it
        found = maintain.check_state(False, self.home, self.LIMITS)
        self.assertIn("1 log(s) over 100 bytes", found[0].text)
        found = maintain.check_state(True, self.home, self.LIMITS)
        self.assertTrue(found[0].fixed)
        self.assertEqual(lines[-11:], log.read_text().splitlines(keepends=True))

    def test_a_log_written_within_the_last_hour_is_left_for_a_quieter_run(self):
        log = self.home / "maintenance.log"
        log.write_text("".join(f"line {n:03d}\n" for n in range(40)))
        self.assertEqual([], maintain.check_state(True, self.home, self.LIMITS))
        self.assertEqual(360, log.stat().st_size)

    def test_a_clean_home_reports_nothing(self):
        (self.home / "maintenance.log").write_text("short\n")
        self.assertEqual([], maintain.check_state(True, self.home, self.LIMITS))

    def test_health_fails_over_the_entry_limit_and_passes_under_it(self):
        for n in range(3):
            (self.home / f"entry-{n}").write_text("x")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            over = health_checks._check_state_folder(self.home, {**self.LIMITS, "stateEntries": 2})
            under = health_checks._check_state_folder(self.home, self.LIMITS)
        self.assertEqual((0, 1, 0), over)
        self.assertEqual((1, 0, 0), under)
        self.assertIn("[FAIL]", out.getvalue())
        self.assertIn("maintain --fix", out.getvalue())

    def test_the_health_command_runs_the_state_folder_check(self):
        from lib import cmd_health
        with mock.patch.object(cmd_health, "_check_state_folder", return_value=(0, 1, 0)) as check:
            with mock.patch.object(cmd_health, "_claude_dir", lambda: self.home / ".claude"):
                quiet(cmd_health.command_health)
        check.assert_called_once_with()

    def test_health_reads_its_limits_from_the_limits_file(self):
        limits = health_checks.state_limits(REPO_ROOT)
        self.assertEqual({"stateEntries", "stateBytes", "stateLogBytes"}, set(limits))
        self.assertTrue(all(isinstance(v, int) for v in limits.values()))


if __name__ == "__main__":
    unittest.main()
