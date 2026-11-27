"""Install links olivercode onto the PATH and writes no validate-queue file (#1315). Every test runs in a temp HOME."""

import os
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script, quiet, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher_shim")
from lib import cmd_install, cmd_health, queue_shim  # noqa: E402



class HomeCase(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self, "oc-shim-home-", resolve=True)
        self.enterContext(mock.patch.object(Path, "home", staticmethod(lambda: self.home)))
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.home)}))
        self.enterContext(mock.patch.object(cmd_install, "_unset_hooks", return_value=([], False)))  # REPO_ROOT keeps its own core.hooksPath
        self.bin = self.home / ".local" / "bin"
        self.shim = self.bin / "validate-queue"

    def install(self):
        return quiet(cmd_install.command_install, REPO_ROOT)


class TestInstall(HomeCase):
    def test_install_links_olivercode_and_writes_no_validate_queue_file(self):
        code, out = self.install()
        self.assertEqual(0, code, out)
        self.assertEqual(REPO_ROOT.resolve() / "scripts" / "olivercode", (self.bin / "olivercode").resolve())
        self.assertFalse(self.shim.exists())
        self.assertNotIn("validate-queue", out)


class TestHealth(HomeCase):
    def test_health_checks_the_olivercode_link_and_not_the_shim(self):
        self.install()
        with mock.patch.object(cmd_health, "_claude_dir", lambda: self.home / ".claude"):
            out = quiet(cmd_health.command_health)[1]
        self.assertNotIn("validate-queue", out)
        self.assertIsNone(queue_shim.launcher_problem(REPO_ROOT))


if __name__ == "__main__":
    unittest.main()
