"""`olivercode update` re-runs install after the pull.

A pull can add a skill or a Claude Code hook, and only install links those into ~/.claude.
Before update ran install, a second device pulled four new skills and had no link to them.
"""

import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
loader = SourceFileLoader("olivercode_update", str(REPO_ROOT / "scripts" / "olivercode"))
spec = importlib.util.spec_from_loader("olivercode_update", loader)
launcher = importlib.util.module_from_spec(spec)
loader.exec_module(launcher)


class UpdateRunsInstall(unittest.TestCase):
    def run_update(self, codes):
        """codes: the exit code for pull, install and sync-hooks, in order."""
        calls = []

        def fake_run(argv, **kwargs):
            calls.append("pull" if argv[:2] == ["git", "-C"] else argv[-1])
            return mock.Mock(returncode=codes[len(calls) - 1])
        with mock.patch.object(launcher.subprocess, "run", side_effect=fake_run):
            return launcher.command_update(), calls

    def test_a_pull_is_followed_by_install_then_hook_sync_in_new_processes(self):
        self.assertEqual(self.run_update([0, 0, 0]), (0, ["pull", "install", "sync-hooks"]))

    def test_install_and_sync_run_the_launcher_the_pull_updated(self):
        argvs = []
        with mock.patch.object(launcher.subprocess, "run",
                               side_effect=lambda argv, **kw: argvs.append(argv) or mock.Mock(returncode=0)):
            launcher.command_update()
        self.assertTrue(all(a[1].endswith("scripts/olivercode") for a in argvs[1:]), argvs)

    def test_a_failed_pull_installs_nothing(self):
        self.assertEqual(self.run_update([1, 0, 0]), (1, ["pull"]))

    def test_a_failed_install_fails_the_update_after_hooks_still_sync(self):
        self.assertEqual(self.run_update([0, 1, 0]), (1, ["pull", "install", "sync-hooks"]))


if __name__ == "__main__":
    unittest.main()
