"""The OliverCode home is private to its user, and repo names reach only ignored files (story 690)."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script

failure_log = load_script("scripts/lib/failure_log.py", "failure_log")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class PrivateHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "oc-home"

    def test_a_fresh_home_is_created_mode_700(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}):
            self.assertEqual(self.home, failure_log.home())
        self.assertEqual(0o700, mode(self.home))

    def test_an_existing_open_home_and_its_files_are_tightened(self):
        (self.home / "land").mkdir(parents=True)
        for path in (self.home / "relays.jsonl", self.home / "land" / "land1.log"):
            path.write_text("words\n")
            path.chmod(0o644)
        self.home.chmod(0o755)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}):
            failure_log.home()
        self.assertEqual(0o700, mode(self.home))
        self.assertEqual(0o700, mode(self.home / "land"))
        self.assertEqual(0o600, mode(self.home / "relays.jsonl"))
        self.assertEqual(0o600, mode(self.home / "land" / "land1.log"))

    def test_a_file_written_through_record_is_mode_600(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}):
            os.environ.pop("OLIVERCODE_FAILURE_LOG", None)
            failure_log.record("Secrets", "BLOCKED", "repo")
            failure_log.home()
        self.assertEqual(0o600, mode(self.home / "failures.log"))


class RepoNamesStayLocal(unittest.TestCase):
    def test_the_local_registry_file_is_ignored_and_the_tracked_one_is_not(self):
        def ignored(rel):
            return subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT).returncode == 0
        self.assertTrue(ignored("shared/repo-profiles.local.json"))
        self.assertFalse(ignored("shared/repo-profiles.json"))

    def test_the_fleet_template_ignores_local_state(self):
        text = (REPO_ROOT / "core" / "templates" / "project" / ".gitignore").read_text().split()
        for entry in (".claude-optimization/audits/", ".claude-optimization/scratch/", "olivercode.local.json", "scratch/"):
            self.assertIn(entry, text)

    def test_the_checkout_ignores_scratch_and_audits(self):
        text = (REPO_ROOT / ".gitignore").read_text().split()
        for entry in (".claude-optimization/audits/", ".claude-optimization/scratch/", "olivercode.local.json", "scratch/"):
            self.assertIn(entry, text)


if __name__ == "__main__":
    unittest.main()
