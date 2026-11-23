"""The validate-queue shim that install writes, uninstall removes and health checks (#572). Every test runs in a temp HOME."""

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
        self.shim = self.home / ".local" / "bin" / "validate-queue"

    def install(self):
        return quiet(cmd_install.command_install, REPO_ROOT)

    def other_checkout_shim(self):
        self.shim.parent.mkdir(parents=True, exist_ok=True)
        self.shim.write_text("#!/bin/sh\nexec python3 /elsewhere/OC/scripts/lib/validate_queue.py \"$@\"\n")
        self.shim.chmod(0o755)


class TestInstallAndUninstall(HomeCase):
    def test_install_writes_a_two_line_executable_wrapper_and_a_rerun_reports_already(self):
        code, out = self.install()
        self.assertEqual(0, code, out)
        self.assertIn("[LINKED] ~/.local/bin/validate-queue", out)
        lines = self.shim.read_text().splitlines()
        self.assertEqual(2, len(lines), lines)
        self.assertIn(str(REPO_ROOT.resolve() / "scripts" / "lib" / "validate_queue.py"), lines[1])
        self.assertTrue(lines[1].startswith("exec python3 ") and lines[1].endswith('"$@"'))
        self.assertTrue(os.access(self.shim, os.X_OK))
        _, again = self.install()
        self.assertIn("[ALREADY] ~/.local/bin/validate-queue", again)

    def test_the_installed_shim_runs_the_queue(self):
        self.install()
        import subprocess
        out = subprocess.run([str(self.shim), "acquire", "--pid", str(os.getpid())], capture_output=True, text=True,
                             env={**{k: v for k, v in os.environ.items() if "VALIDATE" not in k}, "OLIVERCODE_HOME": str(self.home / "ochome")})
        self.assertTrue(out.stdout.strip().endswith("slot-1.json"), out.stdout + out.stderr)

    def test_an_existing_foreign_file_is_backed_up_and_reported(self):
        self.shim.parent.mkdir(parents=True)
        self.shim.write_text("my own helper\n")
        _, out = self.install()
        backup = self.shim.with_name("validate-queue.pre-olivercode")
        self.assertEqual("my own helper\n", backup.read_text())
        self.assertIn("[BACKED-UP] ~/.local/bin/validate-queue", out)
        self.assertIn(str(backup), out)
        self.assertNotEqual("my own helper\n", self.shim.read_text())

    def test_a_shim_for_another_checkout_is_backed_up_and_replaced(self):
        self.other_checkout_shim()
        self.install()
        self.assertTrue(self.shim.with_name("validate-queue.pre-olivercode").is_file())
        self.assertIsNone(queue_shim.problem(REPO_ROOT))

    def test_uninstall_removes_the_shim(self):
        self.install()
        _, out = quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertFalse(self.shim.exists())
        self.assertIn("[REMOVED] ~/.local/bin/validate-queue", out)

    def test_uninstall_restores_the_file_that_was_there_before_install(self):
        self.shim.parent.mkdir(parents=True)
        self.shim.write_text("my own helper\n")
        self.install()
        _, out = quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertEqual("my own helper\n", self.shim.read_text())
        self.assertIn("[RESTORED] ~/.local/bin/validate-queue", out)

    def test_uninstall_keeps_a_shim_that_is_not_this_checkouts(self):
        self.other_checkout_shim()
        _, out = quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertTrue(self.shim.is_file())
        self.assertIn("[KEPT]", out)


class TestHealth(HomeCase):
    def health(self):
        with mock.patch.object(cmd_health, "_claude_dir", lambda: self.home / ".claude"):
            return quiet(cmd_health.command_health)[1]

    def line(self, out):
        return [l for l in out.splitlines() if "validate-queue" in l]

    def test_a_missing_shim_fails_and_names_install(self):
        self.install()
        self.shim.unlink()
        lines = self.line(self.health())
        self.assertEqual(1, len(lines), lines)
        self.assertTrue(lines[0].lstrip().startswith("[FAIL]") and "olivercode install" in lines[0], lines)

    def test_a_shim_for_another_checkout_fails_and_names_install(self):
        self.install()
        self.shim.unlink()
        self.other_checkout_shim()
        lines = self.line(self.health())
        self.assertTrue(lines[0].lstrip().startswith("[FAIL]") and "/elsewhere/OC" in lines[0] and "olivercode install" in lines[0], lines)

    def test_a_current_shim_passes(self):
        self.install()
        self.assertTrue(self.line(self.health())[0].lstrip().startswith("[OK]"))

    def test_a_machine_install_never_linked_is_not_checked(self):
        self.assertEqual([], self.line(self.health()))


if __name__ == "__main__":
    unittest.main()
