"""Learning proposals, agent jobs, memory and version health, and the voice override."""

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
from lib import cmd_harness, failure_log, health_checks, local_config  # noqa: E402


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


class TestLearn(Base):
    def log(self, n, reason="BLOCKED: a.py matches secret pattern: sk-"):
        for _ in range(n):
            failure_log.record("Secrets", reason, "repo")

    def test_three_of_the_same_failure_yield_a_proposal_with_the_evidence(self):
        self.log(3)
        code, text = run(failure_log.command_learn, [])
        self.assertEqual(code, 0)
        self.assertIn("Proposal", text)
        self.assertEqual(text.count("\trepo\tSecrets\t"), 3)

    def test_the_same_failure_in_different_files_counts_together(self):
        for name in ("a.py", "b/c.py", "d.txt"):
            failure_log.record("Secrets", f"BLOCKED: {name} matches secret pattern: sk-", "repo")
        self.assertIn("Proposal", run(failure_log.command_learn, [])[1])

    def test_two_failures_print_nothing_due_and_change_no_file(self):
        self.log(2)
        before = (self.home / "failures.log").read_text()
        self.assertEqual(run(failure_log.command_learn, []), (0, "Nothing due\n"))
        self.assertEqual((self.home / "failures.log").read_text(), before)
        self.assertFalse((self.home / "rejected.txt").exists())

    def test_a_rejected_proposal_is_not_offered_again(self):
        self.log(3)
        k = failure_log.proposals()[0][0]
        run(failure_log.command_learn, ["--reject", k])
        self.assertEqual(run(failure_log.command_learn, [])[1], "Nothing due\n")

    def test_accepting_records_the_proposal_and_stops_it_returning(self):
        self.log(3)
        k = failure_log.proposals()[0][0]
        self.assertEqual(run(failure_log.command_learn, ["--accept", k])[0], 0)
        self.assertIn(k, (self.home / "accepted.txt").read_text())
        self.assertEqual(run(failure_log.command_learn, [])[1], "Nothing due\n")
        self.assertEqual(run(failure_log.command_learn, ["--accept"])[0], 1)


class TestJob(Base):
    def test_an_ungoverned_repo_is_refused_and_named(self):
        repo = temp_dir(self)
        scratch_repo(repo)
        code, text = run(cmd_harness.command_job, [str(repo), "--", "true"])
        self.assertEqual(code, 1)
        self.assertIn("does not govern", text)

    def test_a_governed_repo_runs_the_job_and_a_failed_run_is_logged(self):
        repo = temp_dir(self)
        scratch_repo(repo)
        (repo / ".githooks").mkdir()
        hook = repo / ".githooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        git(repo, "config", "core.hooksPath", ".githooks")
        self.assertEqual(run(cmd_harness.command_job, [str(repo), "--", "true"])[0], 0)
        self.assertEqual(failure_log.entries(), [])
        self.assertEqual(run(cmd_harness.command_job, [str(repo), "--", "false"])[0], 1)
        self.assertEqual(failure_log.entries()[0][2], "job")


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
