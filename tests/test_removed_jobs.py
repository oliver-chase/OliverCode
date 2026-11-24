"""Install removes the launchd jobs of commands the engine no longer has, and the CLI lists none of them (#905)."""

import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, load_script, temp_dir

load_script("scripts/olivercode", "olivercode_removed_jobs")
from lib import cmd_install  # noqa: E402


class TestRemovedJobs(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self, "oc-removed-jobs-")
        self.agents = self.home / "Library" / "LaunchAgents"
        self.agents.mkdir(parents=True)

    def test_an_installed_job_of_a_removed_command_is_unloaded_and_deleted(self):
        for label in cmd_install.REMOVED_JOBS:
            (self.agents / f"{label}.plist").write_text("<plist/>")
        (self.agents / "com.olivercode.board-sweep.plist").write_text("<plist/>")
        ran = []
        gone = cmd_install.retire_removed_jobs(self.home, run=lambda argv, **_: ran.append(argv))
        self.assertEqual(list(cmd_install.REMOVED_JOBS), gone)
        self.assertEqual(["com.olivercode.board-sweep.plist"], sorted(p.name for p in self.agents.iterdir()))
        self.assertEqual(len(cmd_install.REMOVED_JOBS), len(ran))
        self.assertTrue(all(argv[:2] == ["launchctl", "bootout"] for argv in ran))

    def test_the_review_job_is_unloaded_and_deleted_by_install_and_update(self):
        self.assertIn("com.olivercode.review", cmd_install.REMOVED_JOBS)
        plist = self.agents / "com.olivercode.review.plist"
        plist.write_text("<plist/>")
        ran = []
        self.assertEqual(["com.olivercode.review"], cmd_install.retire_removed_jobs(self.home, run=lambda argv, **_: ran.append(argv)))
        self.assertFalse(plist.exists())
        self.assertEqual("com.olivercode.review", ran[0][2].split("/")[-1])

    def test_the_gap_sweep_burndown_and_sweep_jobs_are_unloaded_and_deleted_and_their_commands_are_gone(self):
        labels = ("com.olivercode.gap-sweep", "com.olivercode.burndown", "com.olivercode.sweep")
        for label in labels:
            self.assertIn(label, cmd_install.REMOVED_JOBS)
            (self.agents / f"{label}.plist").write_text("<plist/>")
        ran = []
        self.assertEqual(sorted(labels), sorted(cmd_install.retire_removed_jobs(self.home, run=lambda argv, **_: ran.append(argv))))
        self.assertEqual([], list(self.agents.iterdir()))
        self.assertEqual(sorted(labels), sorted(argv[2].split("/")[-1] for argv in ran))
        for command in ("gap-sweep", "board burndown", "board sweep"):
            done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), *command.split()], capture_output=True, text=True)
            self.assertNotEqual(0, done.returncode, command)
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "cmd_gapsweep.py").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "cmd_burndown.py").exists())

    def test_the_hourly_lesson_job_is_unloaded_and_deleted_and_its_command_is_gone(self):
        label = "com.olivercode.lessons"
        self.assertIn(label, cmd_install.REMOVED_JOBS)
        (self.agents / f"{label}.plist").write_text("<plist/>")
        ran = []
        self.assertEqual([label], cmd_install.retire_removed_jobs(self.home, run=lambda argv, **_: ran.append(argv)))
        self.assertEqual([], list(self.agents.iterdir()))
        self.assertEqual(label, ran[0][2].split("/")[-1])
        for command in ("retro", "cutlist", "usage", "eval"):
            done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), command], capture_output=True, text=True)
            self.assertNotEqual(0, done.returncode, command)
        listing = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True).stdout
        for command in ("olivercode retro", "olivercode cutlist", "olivercode usage", "olivercode eval"):
            self.assertNotIn(command, listing)

    def test_the_rule_command_is_gone(self):
        """cmd_rule had no caller: 0 runs in commands.log (#1054's evidence), so the command and its module are gone (#1124)."""
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "rule", "check", "--repo", "."], capture_output=True, text=True)
        self.assertNotEqual(0, done.returncode)
        listing = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True).stdout
        self.assertNotIn("olivercode rule", listing)
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "cmd_rule.py").exists())

    def test_a_second_run_finds_nothing_to_remove(self):
        self.assertEqual([], cmd_install.retire_removed_jobs(self.home, run=mock.Mock()))

    def test_an_installed_page_of_a_removed_command_is_deleted_and_a_second_run_finds_nothing(self):
        page = self.home / ".olivercode" / "city.html"
        page.parent.mkdir()
        page.write_text("<html/>")
        self.assertEqual([".olivercode/city.html"], cmd_install.retire_removed_pages(self.home))
        self.assertFalse(page.exists())
        self.assertEqual([], cmd_install.retire_removed_pages(self.home))

    def test_install_runs_the_removal(self):
        with mock.patch.object(cmd_install, "retire_removed_jobs") as retired, \
                mock.patch.object(cmd_install, "retire_removed_pages") as pages, \
                mock.patch.object(cmd_install.sys, "platform", "darwin"), \
                mock.patch.object(cmd_install.pwd, "getpwuid", return_value=mock.Mock(pw_dir=str(cmd_install.Path.home()))):
            cmd_install._retire_removed_jobs()
        retired.assert_called_once_with()
        pages.assert_called_once_with()

    def test_the_help_lists_no_city_command(self):
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True)
        words = done.stdout.lower().split()
        self.assertNotIn("city", words)
        self.assertNotIn("workmap", words)
        self.assertNotIn("olivercode city", done.stdout.lower())


if __name__ == "__main__":
    unittest.main()
