"""The olivercode command on PATH: `olivercode` runs from any new zsh or bash shell after install (#777). Every test runs in a temp HOME."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script, quiet, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher_path")
from lib import cmd_install, cmd_health, queue_shim  # noqa: E402

BASE_PATH = "/usr/bin:/bin"


class PathCase(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self, "oc-path-home-", resolve=True)
        self.enterContext(mock.patch.object(Path, "home", staticmethod(lambda: self.home)))
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.home), "PATH": BASE_PATH}))
        self.link = self.home / ".local" / "bin" / "olivercode"

    def install(self):
        return quiet(cmd_install.command_install, REPO_ROOT)

    def shell_finds(self, shell, *flags):
        """Run a real new shell with a clean environment and return what `command -v olivercode` prints."""
        exe = shutil.which(shell)
        if not exe:
            self.skipTest(f"{shell} is not installed")
        env = {"HOME": str(self.home), "PATH": BASE_PATH, "ZDOTDIR": str(self.home)}
        out = subprocess.run([exe, *flags, "-c", "command -v olivercode"], env=env, capture_output=True, text=True)
        return out.stdout.strip()


class TestInstall(PathCase):
    def test_install_links_the_launcher_to_this_checkout(self):
        code, out = self.install()
        self.assertEqual(0, code, out)
        self.assertEqual(REPO_ROOT.resolve() / "scripts" / "olivercode", Path(os.readlink(self.link)))
        self.assertIn("[LINKED] ~/.local/bin/olivercode", out)
        self.assertIn("[ALREADY] ~/.local/bin/olivercode", self.install()[1])

    def test_every_new_zsh_and_bash_shell_finds_it(self):
        self.install()
        want = str(self.link)
        for shell, flags in (("zsh", ()), ("zsh", ("-l",)), ("bash", ("-l",)), ("bash", ("-i",))):
            with self.subTest(shell=shell, flags=flags):
                self.assertEqual(want, self.shell_finds(shell, *flags))

    def test_no_profile_line_when_local_bin_is_already_on_the_path(self):
        os.environ["PATH"] = f"{self.home}/.local/bin:{BASE_PATH}"
        self.install()
        self.assertFalse(any(f.exists() for f in queue_shim.profile_files()))

    def test_a_rerun_does_not_repeat_the_profile_block(self):
        self.install()
        self.install()
        for f in queue_shim.profile_files():
            self.assertEqual(1, f.read_text().count(queue_shim.BLOCK_START), f)

    def test_no_startup_file_for_a_shell_the_machine_lacks(self):
        with mock.patch.object(queue_shim.shutil, "which", lambda name: None if name == "zsh" else "/bin/" + name):
            self.install()
            self.assertFalse((self.home / ".zshenv").exists())
            self.assertTrue((self.home / ".bashrc").exists())
            self.assertIsNone(queue_shim.launcher_problem(REPO_ROOT))

    def test_a_moved_checkout_replaces_the_stale_link(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/old/place/OliverCode/scripts/olivercode")
        self.install()
        self.assertEqual(REPO_ROOT.resolve() / "scripts" / "olivercode", Path(os.readlink(self.link)))
        self.assertEqual([], list(self.link.parent.glob("olivercode.pre-olivercode*")))

    def test_a_foreign_file_is_backed_up(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text("mine\n")
        _, out = self.install()
        self.assertEqual("mine\n", self.link.with_name("olivercode.pre-olivercode").read_text())
        self.assertIn("[BACKED-UP]", out)


class TestUninstall(PathCase):
    def test_a_new_shell_finds_nothing_after_uninstall(self):
        self.install()
        self.assertTrue(self.shell_finds("zsh"))
        quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertFalse(self.link.is_symlink())
        for shell, flags in (("zsh", ()), ("bash", ("-l",))):
            self.assertEqual("", self.shell_finds(shell, *flags))

    def test_uninstall_keeps_text_the_person_wrote_in_their_profile(self):
        zshenv = self.home / ".zshenv"
        zshenv.write_text("export KEEP=1\n")
        self.install()
        quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertEqual("export KEEP=1\n", zshenv.read_text())

    def test_uninstall_keeps_a_file_that_is_not_an_olivercode_link(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text("mine\n")
        _, out = quiet(cmd_install.command_uninstall, REPO_ROOT)
        self.assertEqual("mine\n", self.link.read_text())
        self.assertIn("[KEPT] ~/.local/bin/olivercode", out)


class TestHealth(PathCase):
    def health(self):
        with mock.patch.object(cmd_health, "_claude_dir", lambda: self.home / ".claude"):
            return quiet(cmd_health.command_health)[1]

    def lines(self, out):
        return [l for l in out.splitlines() if "`olivercode`" in l]

    def test_a_reachable_launcher_passes(self):
        self.install()
        self.assertTrue(self.lines(self.health())[0].lstrip().startswith("[OK]"))

    def test_a_missing_link_fails_and_names_install(self):
        self.install()
        self.link.unlink()
        line = self.lines(self.health())[0]
        self.assertTrue(line.lstrip().startswith("[FAIL]") and "olivercode install" in line, line)

    def test_a_link_without_a_path_entry_fails_and_names_install(self):
        self.install()
        for f in queue_shim.profile_files():
            f.unlink()
        line = self.lines(self.health())[0]
        self.assertTrue(line.lstrip().startswith("[FAIL]") and "not on the PATH" in line and "olivercode install" in line, line)


if __name__ == "__main__":
    unittest.main()
