"""Tests for the launcher's command surface: `init` and argument handling.

`init` seeds the gitignored local/ overlay for a fork. It is the command a confused
operator is most likely to re-run, so "never overwrites an existing local/ file" is a
correctness property, not a nicety -- that file holds their real fleet.

Argument handling gets tests because ignoring an unknown flag silently produced a
*wrong success*: `sync-hooks --root /somewhere` ignored the flag, synced the default
fleet, and printed "6 target(s) synced".
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "olivercode"


def _load():
    loader = SourceFileLoader("olivercode_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("olivercode_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = _load()


class TestInit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-init-"))
        (self.tmp / "shared").mkdir()
        for rel in ("repo-profiles.example.json", "repo-map.json", "project-structure-rules.json"):
            shutil.copy2(REPO_ROOT / "shared" / rel, self.tmp / "shared" / rel)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seeds_local_from_examples(self):
        rc = launcher.command_init(self.tmp)
        self.assertEqual(rc, 0)
        for rel in ("repo-profiles.json", "repo-map.json", "project-structure-rules.json"):
            self.assertTrue((self.tmp / "local" / rel).is_file(), f"local/{rel} not created")

    def test_never_overwrites_existing_local_file(self):
        """The operator's real fleet config must survive a re-run."""
        local = self.tmp / "local"
        local.mkdir()
        real = local / "repo-profiles.json"
        real.write_text('{"profiles": {"my-real-repo": {}}}', encoding="utf-8")

        launcher.command_init(self.tmp)

        preserved = json.loads(real.read_text())
        self.assertIn("my-real-repo", preserved["profiles"])

    def test_is_idempotent(self):
        self.assertEqual(launcher.command_init(self.tmp), 0)
        self.assertEqual(launcher.command_init(self.tmp), 0)

    def test_reports_failure_when_an_example_is_missing(self):
        (self.tmp / "shared" / "repo-map.json").unlink()
        self.assertEqual(launcher.command_init(self.tmp), 1)


class TestRootFlag(unittest.TestCase):
    def test_extracts_root_and_leaves_remaining_args(self):
        root, rest = launcher._take_root_flag(["--root", "/tmp", "extra"])
        self.assertEqual(root, Path("/tmp"))
        self.assertEqual(rest, ["extra"])

    def test_absent_root_returns_none(self):
        root, rest = launcher._take_root_flag(["something"])
        self.assertIsNone(root)
        self.assertEqual(rest, ["something"])

    def test_missing_value_exits(self):
        with self.assertRaises(SystemExit):
            launcher._take_root_flag(["--root"])

    def test_nonexistent_directory_exits(self):
        with self.assertRaises(SystemExit):
            launcher._take_root_flag(["--root", "/definitely/not/a/dir"])


class TestUnknownArgsRejected(unittest.TestCase):
    """An ignored flag is a wrong success. These must fail loudly."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *args],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )

    def test_sync_hooks_rejects_unknown_flag(self):
        result = self._run("sync-hooks", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)

    def test_health_rejects_unknown_flag(self):
        result = self._run("health", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)

    def test_init_rejects_unknown_flag(self):
        result = self._run("init", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)

    def test_invalid_command_still_fails(self):
        result = self._run("not-a-command")
        self.assertNotEqual(result.returncode, 0)

    def test_help_aliases_all_exit_zero(self):
        for args in ([], ["--help"], ["-h"], ["help"]):
            self.assertEqual(self._run(*args).returncode, 0, f"{args} should exit 0")


if __name__ == "__main__":
    unittest.main()
