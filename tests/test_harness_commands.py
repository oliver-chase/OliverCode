"""The gate-block report, memory and version health, and the voice override."""

import json
import os
import subprocess
import unittest
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir
from _support import quiet as run

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import failure_log, health_checks, local_config  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log")})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestFailureLog(Base):
    def test_a_log_past_twice_its_kept_size_keeps_only_its_newest_lines(self):
        path = failure_log.log_path()
        path.write_text("".join(f"line {i}\n" for i in range(2 * failure_log.KEEP_LINES)))
        failure_log.record("Secrets", "BLOCKED", "r")
        lines = path.read_text().splitlines()
        self.assertEqual(failure_log.KEEP_LINES, len(lines))
        self.assertIn("Secrets", lines[-1])


class TestMemoryAndVersion(Base):
    def make(self, text):
        root = temp_dir(self)
        (root / ".claude-optimization" / "memory").mkdir(parents=True)
        (root / ".claude-optimization" / "memory" / "MEMORY.md").write_text(text)
        return root

    def test_memory_over_budget_fails_and_names_the_largest_file(self):
        root = self.make("word " * 50)
        out = run(health_checks._check_memory, root, 10)
        self.assertEqual(out[0][1], 1)
        self.assertIn("MEMORY.md (50)", out[1])

    def test_a_stale_path_is_listed_and_nothing_is_deleted(self):
        root = self.make("See `" + "scripts/" + "gone.py` for details.")
        (root / "scripts").mkdir()
        (root / "scripts" / "here.py").write_text("")
        result, text = run(health_checks._check_memory, root)
        self.assertIn("scripts/gone.py", text)
        self.assertEqual(result[2], 1)
        self.assertTrue((root / ".claude-optimization" / "memory" / "MEMORY.md").exists())

    def test_a_checkout_behind_upstream_prints_the_count_and_the_log(self):
        up = temp_dir(self)
        scratch_repo(up, branch="main")
        (up / "a.txt").write_text("a")
        git(up, "add", "."); git(up, "commit", "-q", "-m", "first")
        fork = temp_dir(self)
        subprocess.run(["git", "clone", "-q", str(up), str(fork)], check=True)
        git(fork, "remote", "rename", "origin", "upstream")
        (up / "x.txt").write_text("x")
        git(up, "add", "."); git(up, "commit", "-q", "-m", "Closed #99")
        git(fork, "fetch", "-q", "upstream")
        result, text = run(health_checks._check_commits_behind, fork)
        self.assertIn("1 commit(s) behind upstream/main", text)
        self.assertIn("Closed #99", text)
        self.assertEqual(result, (0, 0, 1))

    def test_a_level_checkout_is_ok_and_one_with_no_remote_checks_nothing(self):
        fork = temp_dir(self)
        scratch_repo(fork)
        result, text = run(health_checks._check_commits_behind, fork)
        self.assertEqual(result, (0, 0, 0))
        self.assertIn("not counted", text)


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
