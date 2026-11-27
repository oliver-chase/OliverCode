"""Maintain removes the launchd jobs of commands the engine no longer has, and the CLI lists none of them (#905)."""

import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, load_script, temp_dir

load_script("scripts/olivercode", "olivercode_removed_jobs")
from lib import cmd_install, maintain  # noqa: E402


class TestRemovedJobs(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self, "oc-removed-jobs-")
        self.agents = self.home / "Library" / "LaunchAgents"
        self.agents.mkdir(parents=True)

    def test_an_installed_job_of_a_removed_command_is_unloaded_and_deleted(self):
        for label in cmd_install.REMOVED_JOBS:
            (self.agents / f"{label}.plist").write_text("<plist/>")
        (self.agents / "com.olivercode.board-sweep.plist").write_text("<plist/>")
        with mock.patch.object(maintain.subprocess, "run") as ran:
            gone = maintain.check_retired_jobs(True, self.agents)
        self.assertEqual(len(cmd_install.REMOVED_JOBS), len(gone))
        self.assertEqual(["com.olivercode.board-sweep.plist"], sorted(p.name for p in self.agents.iterdir()))
        self.assertEqual(len(cmd_install.REMOVED_JOBS), ran.call_count)
        self.assertTrue(all(c.args[0][:2] == ["launchctl", "bootout"] for c in ran.call_args_list))

    def test_the_gap_sweep_burndown_and_sweep_jobs_are_unloaded_and_deleted_and_their_commands_are_gone(self):
        labels = ("com.olivercode.gap-sweep", "com.olivercode.burndown", "com.olivercode.sweep")
        for label in labels:
            self.assertIn(label, cmd_install.REMOVED_JOBS)
            (self.agents / f"{label}.plist").write_text("<plist/>")
        with mock.patch.object(maintain.subprocess, "run"):
            self.assertEqual(3, len(maintain.check_retired_jobs(True, self.agents)))
        self.assertEqual([], list(self.agents.iterdir()))
        for command in ("gap-sweep", "board burndown", "board sweep"):
            done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), *command.split()], capture_output=True, text=True)
            self.assertNotEqual(0, done.returncode, command)
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "cmd_gapsweep.py").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "lib" / "cmd_burndown.py").exists())

    def test_the_retired_hourly_job_is_unloaded_and_deleted_and_its_command_is_gone(self):
        label = "com.olivercode.lessons"
        self.assertIn(label, cmd_install.REMOVED_JOBS)
        (self.agents / f"{label}.plist").write_text("<plist/>")
        with mock.patch.object(maintain.subprocess, "run"):
            self.assertEqual(1, len(maintain.check_retired_jobs(True, self.agents)))
        self.assertEqual([], list(self.agents.iterdir()))
        for command in ("retro", "cutlist", "usage", "eval"):
            done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), command], capture_output=True, text=True)
            self.assertNotEqual(0, done.returncode, command)
        listing = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True).stdout
        for command in ("olivercode retro", "olivercode cutlist", "olivercode usage", "olivercode eval"):
            self.assertNotIn(command, listing)

    def test_the_help_lists_no_city_command(self):
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True)
        words = done.stdout.lower().split()
        self.assertNotIn("city", words)
        self.assertNotIn("workmap", words)
        self.assertNotIn("olivercode city", done.stdout.lower())


if __name__ == "__main__":
    unittest.main()
