"""The gate-block report, memory and version health, and the voice override."""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, health_checks, local_config  # noqa: E402


def run(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn(*args)
    return code, out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log")})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestReport(Base):
    def test_blocks_are_counted_per_gate(self):
        failure_log.record("Secrets", "BLOCKED", "r")
        failure_log.record("Secrets", "BLOCKED", "r")
        failure_log.record("Size ratchet", "BLOCKED", "r")
        text = run(failure_log.command_report, [])[1]
        self.assertIn("Secrets: 2", text)
        self.assertIn("Size ratchet: 1", text)

    def test_a_non_number_for_days_prints_the_usage_line(self):
        code, text = run(failure_log.command_report, ["--days", "x"])
        self.assertEqual(code, 1)
        self.assertIn("Usage: olivercode report [--days N]", text)


class TestMemoryAndVersion(Base):
    def make(self, text, budget=None):
        root = temp_dir(self)
        (root / ".claude-optimization" / "memory").mkdir(parents=True)
        (root / ".claude-optimization" / "memory" / "MEMORY.md").write_text(text)
        (root / "docs").mkdir()
        (root / "docs" / "BUDGET.json").write_text(json.dumps({"memoryWords": budget}))
        return root

    def test_memory_over_budget_fails_and_names_the_largest_file(self):
        root = self.make("word " * 50, budget=10)
        out = run(health_checks._check_memory, root)
        self.assertEqual(out[0][1], 1)
        self.assertIn("MEMORY.md (50)", out[1])

    def test_a_stale_path_is_listed_and_nothing_is_deleted(self):
        root = self.make("See `" + "scripts/" + "gone.py` for details.", budget=100)
        (root / "scripts").mkdir()
        (root / "scripts" / "here.py").write_text("")
        result, text = run(health_checks._check_memory, root)
        self.assertIn("scripts/gone.py", text)
        self.assertEqual(result[2], 1)
        self.assertTrue((root / ".claude-optimization" / "memory" / "MEMORY.md").exists())

    def test_a_fork_behind_upstream_sees_the_gap_and_missing_entries(self):
        up = temp_dir(self)
        scratch_repo(up, branch="main")
        (up / "VERSION").write_text("0.2.0\n")
        (up / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.0\n\nClosed #99.\n")
        git(up, "add", "."); git(up, "commit", "-q", "-m", "x")
        fork = temp_dir(self)
        scratch_repo(fork)
        git(fork, "remote", "add", "upstream", str(up)); git(fork, "fetch", "-q", "upstream")
        (fork / "VERSION").write_text("0.1.0\n")
        (fork / "CHANGELOG.md").write_text("# Changelog\n")
        result, text = run(health_checks._check_version, fork)
        self.assertIn("0.1.0 differs from upstream 0.2.0", text)
        self.assertIn("Closed #99.", text)

    def test_a_fork_with_no_upstream_checks_nothing(self):
        fork = temp_dir(self)
        scratch_repo(fork)
        (fork / "VERSION").write_text("0.1.0\n")
        self.assertEqual(run(health_checks._check_version, fork)[0], (0, 0, 0))


class TestVoiceOverride(Base):
    def test_default_is_the_shipped_voice_and_an_owner_file_wins(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VOICE_FILE": ""}):
            self.assertEqual(local_config.voice_file(), REPO_ROOT / "docs" / "VOICE.md")
        mine = self.home / "mine.md"
        mine.write_text("my voice")
        with mock.patch.dict(os.environ, {"OLIVERCODE_VOICE_FILE": str(mine)}):
            self.assertEqual(local_config.voice_file(), mine)

    def test_a_missing_owner_file_falls_back_to_the_shipped_voice(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VOICE_FILE": str(self.home / "none.md")}):
            self.assertEqual(local_config.voice_file(), REPO_ROOT / "docs" / "VOICE.md")


if __name__ == "__main__":
    unittest.main()
