"""A blank clone installs and passes health with none of the owner's data (the fast half of scripts/qa/rehearse-install.sh --clone)."""

import os
import re
import subprocess
import unittest
from pathlib import Path

from _support import REAL_HOME, REPO_ROOT, git, git_env, temp_dir


def owner_leaks(root: Path, markers: list[str]) -> list[str]:
    """Tracked files under `root` that hold one of the owner's markers."""
    names = git(root, "ls-files").stdout.splitlines()
    pattern = re.compile("|".join(re.escape(m) for m in markers))
    return [n for n in names if (root / n).is_file() and pattern.search((root / n).read_text(encoding="utf-8", errors="ignore"))]


class TestCleanCloneInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(__import__("tempfile").mkdtemp(prefix="olivercode-clean-clone-"))
        cls.clone = cls.tmp / "OliverCode"
        subprocess.run(["git", "clone", "-q", str(REPO_ROOT), str(cls.clone)], env=git_env(), check=True)
        cls.home = cls.tmp / "home"
        cls.home.mkdir()

    @classmethod
    def tearDownClass(cls):
        __import__("shutil").rmtree(cls.tmp, ignore_errors=True)

    def launcher(self, *args):
        env = git_env(HOME=str(self.home), OLIVERCODE_HOME=str(self.home / ".olivercode"), OLIVERCODE_LOCAL_CONFIG=os.devnull, OLIVERCODE_LAUNCHER=str(self.home / "no-launcher"))
        return subprocess.run(["python3", str(self.clone / "scripts" / "olivercode"), *args], capture_output=True, text=True, env=env)

    def test_install_then_health_exit_zero_with_no_local_config(self):
        install = self.launcher("install")
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertTrue((self.home / ".claude" / "CLAUDE.md").is_symlink())
        health = self.launcher("health")
        self.assertEqual(health.returncode, 0, health.stdout + health.stderr)

    def test_no_tracked_file_holds_this_machines_home_path(self):
        home = (REAL_HOME or "").rstrip("/")
        self.assertTrue(home, "HOME was not set")
        self.assertEqual(owner_leaks(self.clone, [home]), [])

    def test_the_leak_scan_names_a_file_that_holds_a_marker(self):
        repo = temp_dir(self)
        git(repo, "init", "-q")
        (repo / "notes.md").write_text("see /Users/example/private")
        git(repo, "add", ".")
        self.assertEqual(owner_leaks(repo, ["/Users/example"]), ["notes.md"])
