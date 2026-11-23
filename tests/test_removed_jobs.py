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
        (self.agents / "com.olivercode.burndown.plist").write_text("<plist/>")
        ran = []
        gone = cmd_install.retire_removed_jobs(self.home, run=lambda argv, **_: ran.append(argv))
        self.assertEqual(list(cmd_install.REMOVED_JOBS), gone)
        self.assertEqual(["com.olivercode.burndown.plist"], sorted(p.name for p in self.agents.iterdir()))
        self.assertEqual(len(cmd_install.REMOVED_JOBS), len(ran))
        self.assertTrue(all(argv[:2] == ["launchctl", "bootout"] for argv in ran))

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
