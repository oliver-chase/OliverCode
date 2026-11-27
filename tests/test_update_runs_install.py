"""`olivercode update` re-runs install after the pull.

A pull can add a skill or a Claude Code hook, and only install links those into ~/.claude.
Before update ran install, a second device pulled four new skills and had no link to them.
"""

import unittest
from unittest import mock

from _support import load_script

launcher = load_script("scripts/olivercode", "olivercode_update")


class UpdateRunsInstall(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("lib.update_state.rewritten", return_value=False)  # never realign the real checkout
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_update(self, codes):
        """codes: the exit code for pull, install and sync-hooks, in order. The clean-checkout check is
        stubbed here, since this test is about what runs after a pull (tests/test_update_keeps_local_learning.py
        covers the check)."""
        calls = []

        def fake_run(argv, **kwargs):
            calls.append("pull" if argv[:2] == ["git", "-C"] else argv[-1])
            return mock.Mock(returncode=codes[len(calls) - 1])
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch.object(launcher.subprocess, "run", side_effect=fake_run):
            return launcher.command_update(), calls

    def test_a_pull_is_followed_by_install_hook_sync_in_new_processes(self):
        self.assertEqual(self.run_update([0, 0, 0, 0]), (0, ["pull", "install", "sync-hooks"]))

    def test_install_and_sync_run_the_launcher_the_pull_updated(self):
        argvs = []
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch.object(launcher.subprocess, "run",
                                  side_effect=lambda argv, **kw: argvs.append(argv) or mock.Mock(returncode=0)):
            launcher.command_update()
        self.assertTrue(all(a[1].endswith("scripts/olivercode") for a in argvs[1:]), argvs)

    def test_a_story_makes_the_hook_sync_commit(self):
        argvs = []
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch.object(launcher.subprocess, "run",
                                  side_effect=lambda argv, **kw: argvs.append(argv) or mock.Mock(returncode=0)):
            launcher.command_update(story="848")
        sync = next(a for a in argvs if "sync-hooks" in a)
        self.assertEqual(sync[-3:], ["--commit", "--story", "848"])

    def test_a_failed_pull_installs_nothing(self):
        self.assertEqual(self.run_update([1, 0, 0, 0]), (1, ["pull"]))

    def test_a_failed_install_fails_the_update_after_hooks_still_sync(self):
        self.assertEqual(self.run_update([0, 1, 0, 0]), (1, ["pull", "install", "sync-hooks"]))
