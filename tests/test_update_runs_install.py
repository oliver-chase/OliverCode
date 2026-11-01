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
    def run_update(self, pull=0, install=0, sync=0):
        calls = []
        with mock.patch.object(launcher.subprocess, "run", return_value=mock.Mock(returncode=pull)), \
             mock.patch.object(launcher, "command_install", side_effect=lambda root: calls.append("install") or install), \
             mock.patch.object(launcher, "command_sync_hooks", side_effect=lambda root: calls.append("sync") or sync):
            return launcher.command_update(), calls

    def test_a_pull_is_followed_by_install_then_hook_sync(self):
        self.assertEqual(self.run_update(), (0, ["install", "sync"]))

    def test_a_failed_pull_installs_nothing(self):
        self.assertEqual(self.run_update(pull=1), (1, []))

    def test_a_failed_install_fails_the_update_after_hooks_still_sync(self):
        self.assertEqual(self.run_update(install=1), (1, ["install", "sync"]))


if __name__ == "__main__":
    unittest.main()
