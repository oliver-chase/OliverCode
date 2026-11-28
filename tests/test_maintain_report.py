"""olivercode maintain: stale docs, the report, the schedule, tidying and the main checkout."""

import plistlib
import subprocess
import unittest
from unittest import mock

from _maintain_case import Base
from _support import git, git_env, quiet, scratch_repo
from lib import failure_log, hygiene, maintain, placement


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
        self.assertEqual(quiet(maintain.report, problems, True)[0], 1)
        self.assertEqual(failure_log.entries()[0][2], "maintain")
        self.assertIn("NEEDS A DECISION", (self.home / "maintenance.log").read_text())

    def test_a_decision_is_queued_for_the_owner_once_while_it_stays_open(self):
        from lib import cmd_owner
        problems = [maintain.Problem("placement", "repo out of place: /x. move it")]
        quiet(maintain.report, problems, True)
        quiet(maintain.report, problems, True)
        open_steps = [i["step"] for i in cmd_owner.items() if i["status"] == "open"]
        self.assertEqual(["maintain placement: repo out of place: /x. move it"], open_steps)

    def test_everything_fixed_exits_zero_and_logs_no_failure(self):
        self.assertEqual(quiet(maintain.report, [maintain.Problem("links", "x", True, True)], True)[0], 0)
        self.assertEqual(failure_log.entries(), [])

    def test_usage_error_exits_one(self):
        self.assertEqual(quiet(maintain.command_maintain, ["--bogus"])[0], 1)


class TestSchedule(Base):
    def test_the_job_runs_maintain_fix_daily(self):
        job = maintain.plist()
        self.assertEqual(job["ProgramArguments"][-2:], ["maintain", "--fix"])
        self.assertIn("StartCalendarInterval", job)
        plistlib.loads(plistlib.dumps(job))
        from lib.cli import MIN_PYTHON, python_version
        exe = maintain.plist()["ProgramArguments"][0]
        self.assertGreaterEqual(python_version(exe) or (0, 0), MIN_PYTHON)

    def test_an_old_python_is_swapped_for_a_newer_one(self):
        with mock.patch.object(maintain.sys, "version_info", (3, 9, 6)), \
                mock.patch.object(maintain, "newer_python", return_value="/opt/homebrew/bin/python3.15"):
            self.assertEqual(maintain.plist()["ProgramArguments"][0], "/opt/homebrew/bin/python3.15")

    def test_an_old_python_with_no_newer_one_uses_the_python3_on_path(self):
        with mock.patch.object(maintain.sys, "version_info", (3, 9, 6)), \
                mock.patch.object(maintain, "newer_python", return_value=None), \
                mock.patch.object(maintain.shutil, "which", return_value="/opt/x/bin/python3"):
            self.assertEqual(maintain.plist()["ProgramArguments"][0], "/opt/x/bin/python3")


class TestTidy(Base):
    def trees(self):
        a, b, c = (self.root / n for n in ("merged", "dirty", "ahead"))
        for p in (a, b, c):
            scratch_repo(p)
        W = placement.Worktree
        return [W(a, "m", False, True, a), W(b, "d", True, True, b), W(c, "s", False, False, c)]

    def tidy(self, fix, ps="", tasks=None, today="2026-11-20"):
        trees = self.trees()
        clean = mock.Mock(return_value=[f"REMOVE {trees[0].path}"])
        with mock.patch.object(placement, "worktrees", return_value=trees), mock.patch.object(placement, "clean", clean):
            return maintain.check_tidy(self.cfg, fix, ps_text=ps, tasks_dir=tasks or self.claude / "none", today=today), clean

    def test_merged_and_clean_worktrees_are_removed_with_fix_and_only_listed_without(self):
        found, clean = self.tidy(True)
        clean.assert_called_once_with(self.cfg, apply=True, remote=False)
        self.assertTrue(any(p.fixed and "removed 1" in p.text for p in found))
        found, clean = self.tidy(False)
        clean.assert_not_called()
        self.assertFalse(any(p.fixed for p in found))

    def test_a_dirty_worktree_and_one_with_unpushed_commits_are_named_with_their_reason_and_never_removed(self):
        text = " ".join(p.text for p in self.tidy(True)[0])
        self.assertIn("uncommitted changes", text)
        self.assertIn("commits not on the default branch (s)", text)
        self.assertNotIn("merged (", text)

    def test_a_stray_process_older_than_a_day_is_listed_with_age_and_owner_and_another_accounts_is_not(self):
        ps = "11 05:00 me claude\n12 2-03:04:05 me /usr/bin/ffmpeg\n13 3-00:00:01 root launchd\n14 4-00:00:00 other /usr/bin/python3\n"
        with mock.patch("getpass.getuser", return_value="me"):
            text = " ".join(p.text for p in self.tidy(False, ps)[0])
        self.assertIn("process 12 (ffmpeg) owned by me has run 2 day(s)", text)
        self.assertNotIn("process 11", text)
        self.assertNotIn("launchd", text)
        self.assertNotIn("process 14", text)
        self.assertNotIn("other", text)

    def test_a_one_time_task_past_its_date_is_listed_and_deleted_by_nothing(self):
        tasks = self.claude / "tasks"
        for name in ("brief-2026-11-17", "brief-2026-12-01", "daily-check"):
            (tasks / name).mkdir(parents=True)
            (tasks / name / "SKILL.md").write_text("x")
        text = " ".join(p.text for p in self.tidy(True, tasks=tasks)[0])
        self.assertIn("brief-2026-11-17", text)
        self.assertNotIn("2026-12-01", text)
        self.assertTrue((tasks / "brief-2026-11-17" / "SKILL.md").exists())


class TestMainCheckout(Base):
    """A clean checkout fast-forwards to origin/main, and an edited one only reports how far behind it is (#607)."""

    def clone(self):
        origin = self.root / "origin.git"
        scratch_repo(origin, bare=True, branch="main")
        work = self.root / "work"
        scratch_repo(work, branch="main")
        git(work, "remote", "add", "origin", str(origin))
        (work / "a.txt").write_text("a")
        git(work, "add", "."); git(work, "commit", "-q", "-m", "one"); git(work, "push", "-q", "origin", "main")
        mine = self.root / "mine"
        git(self.root, "clone", "-q", str(origin), str(mine))
        (work / "a.txt").write_text("b")
        git(work, "commit", "-qam", "two"); git(work, "push", "-q", "origin", "main")
        return mine

    def test_a_clean_checkout_fast_forwards_and_reports_nothing_after(self):
        mine = self.clone()
        self.assertIn("1 commit(s) behind origin/main and clean", maintain.check_main_checkout(False, mine)[0].text)
        self.assertTrue(maintain.check_main_checkout(True, mine)[0].fixed)
        self.assertEqual([], maintain.check_main_checkout(False, mine))

    def test_an_untracked_file_does_not_make_the_checkout_edited(self):
        mine = self.clone()
        (mine / "scratch.txt").write_text("untracked")
        self.assertEqual((1, "clean"), maintain.main_checkout_lag(mine, fetch=True))

    def test_the_outsider_check_names_a_failure_and_does_not_raise(self):
        with mock.patch("lib.cmd_sweep.boards", side_effect=OSError("no boards")):
            found = maintain.check_outsiders(True)
        self.assertEqual(["outsiders"], [p.step for p in found])
        self.assertIn("no boards", found[0].text)

    def test_the_queue_check_closes_resolved_denials_on_fix_and_files_nothing(self):
        with mock.patch("lib.denials.close_resolved") as close, mock.patch("subprocess.run") as gh:
            self.assertEqual([], maintain.check_queues(False))
            close.assert_not_called()
            self.assertEqual([], maintain.check_queues(True))
        close.assert_called_once_with()
        gh.assert_not_called()

    def test_the_queue_check_names_a_failure_and_does_not_raise(self):
        with mock.patch("lib.denials.close_resolved", side_effect=OSError("disk full")):
            found = maintain.check_queues(True)
        self.assertEqual(["queues"], [p.step for p in found])
        self.assertIn("disk full", found[0].text)

    def test_an_edited_checkout_is_not_touched_and_health_counts_the_commits_behind(self):
        mine = self.clone()
        (mine / "a.txt").write_text("local edit")
        problem = maintain.check_main_checkout(True, mine)[0]
        self.assertFalse(problem.fixed)
        self.assertIn("1 commit(s) behind origin/main and edited", problem.text)
        self.assertEqual("local edit", (mine / "a.txt").read_text())
        self.assertEqual((1, "edited"), maintain.main_checkout_lag(mine))


if __name__ == "__main__":
    unittest.main()
