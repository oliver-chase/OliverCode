"""Tests for the permission policy, its hook, checkpoint and restore, and the context budget."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import checkpoint, context_budget, policy  # noqa: E402

GUARD = REPO_ROOT / "scripts" / "hooks" / "policy_guard.py"


def run_guard(repo, tool_input, log):
    payload = json.dumps({"tool_input": tool_input, "cwd": str(repo)})
    env = {**os.environ, "OLIVERCODE_FAILURE_LOG": str(log)}
    done = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, env=env)
    return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else None


class TestEvaluate(unittest.TestCase):
    def test_an_unlisted_command_is_denied_with_its_rule(self):
        d = policy.evaluate_bash(policy.DEFAULT, "zzz --go")
        self.assertEqual(("deny", "commands.allow"), (d.kind, d.rule))

    def test_a_listed_command_passes(self):
        self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, "git status && ls -la | head"))

    def test_a_wrapped_command_is_read(self):
        self.assertEqual("deny", policy.evaluate_bash(policy.DEFAULT, "bash -c 'zzz now'").kind)

    def test_a_force_push_is_denied_by_pattern(self):
        self.assertEqual("deny", policy.evaluate_bash(policy.DEFAULT, "git push --force origin main").kind)

    def test_a_push_asks(self):
        self.assertEqual(("ask", "triggers.push"), tuple(getattr(policy.evaluate_bash(policy.DEFAULT, "git push"), a) for a in ("kind", "rule")))

    def test_deleting_more_than_ten_files_asks_and_ten_does_not(self):
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "rm " + " ".join(f"f{i}" for i in range(11))).kind)
        self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, "rm " + " ".join(f"f{i}" for i in range(10))))

    def test_a_denied_path_is_refused_and_an_ordinary_one_passes(self):
        root = Path("/repo")
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/.githooks/pre-commit").kind)
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/.env").kind)
        self.assertIsNone(policy.evaluate_path(policy.DEFAULT, root, "/repo/src/a.py"))

    def test_a_path_outside_paths_allow_is_refused(self):
        rules = {"paths": {"allow": ["src/**"], "deny": []}}
        self.assertEqual("deny", policy.evaluate_path(rules, Path("/repo"), "/repo/docs/a.md").kind)
        self.assertIsNone(policy.evaluate_path(rules, Path("/repo"), "/repo/src/deep/a.py"))

    def test_a_third_failed_attempt_at_one_gate_asks(self):
        log = temp_dir(self) / "failures.log"
        stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log.write_text("".join(f"{stamp}\tapp\tsecrets\tBLOCKED\n" for _ in range(2)))
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            d = policy.evaluate_bash(policy.DEFAULT, "git commit -m x", "app")
            self.assertEqual("triggers.gateFailures", d.rule)
            self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, "git commit -m x", "other"))


class TestHook(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, resolve=True)
        self.repo = scratch_repo(self.tmp / "app")
        self.log = self.tmp / "failures.log"

    def test_a_repo_without_a_policy_is_not_restricted(self):
        self.assertIsNone(run_guard(self.repo, {"command": "zzz now"}, self.log))

    def test_a_command_outside_the_policy_is_blocked_and_logged(self):
        policy.write_default(self.repo)
        out = run_guard(self.repo, {"command": "zzz now"}, self.log)
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("commands.allow", out["permissionDecisionReason"])
        self.assertIn("\tapp\tpolicy\tdeny commands.allow", self.log.read_text())

    def test_an_edit_to_a_denied_path_is_blocked(self):
        policy.write_default(self.repo)
        out = run_guard(self.repo, {"file_path": str(self.repo / ".env")}, self.log)
        self.assertEqual("deny", out["permissionDecision"])

    def test_a_push_asks_the_owner(self):
        policy.write_default(self.repo)
        out = run_guard(self.repo, {"command": "git push origin main"}, self.log)
        self.assertEqual("ask", out["permissionDecision"])

    def test_an_allowed_command_stays_silent(self):
        policy.write_default(self.repo)
        self.assertIsNone(run_guard(self.repo, {"command": "ls"}, self.log))

    def test_garbage_input_fails_open(self):
        done = subprocess.run([sys.executable, str(GUARD)], input="nope", capture_output=True, text=True)
        self.assertEqual((0, ""), (done.returncode, done.stdout))


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, resolve=True)
        self.repo = scratch_repo(self.tmp / "app", branch="main")
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-q", "-m", "first")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_restore_undoes_a_run_that_committed_edited_and_added_files(self):
        before = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        (self.repo / "kept.txt").write_text("was here\n")
        checkpoint.take(self.repo)
        (self.repo / "a.txt").write_text("changed\n")
        git(self.repo, "commit", "-aq", "-m", "run")
        (self.repo / "new").mkdir()
        (self.repo / "new" / "b.txt").write_text("stray\n")
        text = checkpoint.restore(self.repo)
        self.assertEqual(before, git(self.repo, "rev-parse", "HEAD").stdout.strip())
        self.assertEqual("one\n", (self.repo / "a.txt").read_text())
        self.assertFalse((self.repo / "new").exists())
        self.assertTrue((self.repo / "kept.txt").exists())
        self.assertIn("Removed new/b.txt", text)

    def test_uncommitted_changes_at_checkpoint_come_back(self):
        (self.repo / "a.txt").write_text("dirty\n")
        checkpoint.take(self.repo)
        (self.repo / "a.txt").write_text("worse\n")
        checkpoint.restore(self.repo)
        self.assertEqual("dirty\n", (self.repo / "a.txt").read_text())

    def test_restore_without_a_checkpoint_stops(self):
        self.assertTrue(checkpoint.restore(self.repo).startswith("Stopped"))


class TestContextBudget(unittest.TestCase):
    def setUp(self):
        self.claude = temp_dir(self)
        (self.claude / "CLAUDE.md").write_text("word " * 100)
        (self.claude / "VOICE.md").write_text("word " * 300)
        patcher = mock.patch.object(context_budget, "claude_dir", lambda: self.claude)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_within_budget_prints_the_total_and_passes(self):
        with mock.patch.object(context_budget, "budget", lambda: 500):
            ok, text = context_budget.report()
        self.assertTrue(ok)
        self.assertIn("400 words, within the budget of 500", text)

    def test_over_budget_fails_and_names_the_largest_file_first(self):
        with mock.patch.object(context_budget, "budget", lambda: 300):
            ok, text = context_budget.report()
        self.assertFalse(ok)
        self.assertLess(text.index("VOICE.md"), text.index("CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
