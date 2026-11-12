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


ALLOW_GIT = {"commands": {"allow": ["git", "ls", "head"], "deny": []}}


class TestEvaluate(unittest.TestCase):
    def test_an_unlisted_command_is_denied_with_its_rule_when_the_policy_has_an_allow_list(self):
        d = policy.evaluate_bash(ALLOW_GIT, "zzz --go")
        self.assertEqual(("deny", "commands.allow"), (d.kind, d.rule))

    def test_a_listed_command_passes(self):
        self.assertIsNone(policy.evaluate_bash(ALLOW_GIT, "git status && ls -la | head"))

    def test_a_wrapped_command_is_read(self):
        self.assertEqual("deny", policy.evaluate_bash(ALLOW_GIT, "bash -c 'zzz now'").kind)

    def test_the_default_policy_allows_ordinary_commands(self):
        for command in ("which git", "curl -s example.test", "docker ps", "timeout 600 pytest -q", "nice -n 5 pytest -q", "sudo -u root ls"):
            self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, command), command)

    def test_a_wrapper_does_not_hide_the_command_it_runs(self):
        for command in ("timeout 9 zzz", "nice -n 5 zzz", "env -i FOO=1 zzz"):
            self.assertEqual("deny", policy.evaluate_bash(ALLOW_GIT, command).kind, command)

    def test_a_force_push_is_denied_in_every_spelling_and_a_lease_is_not(self):
        for command in ("git push --force origin main", "git push -f origin main", "git push origin main -f", "git push -fu origin main"):
            self.assertEqual("deny", policy.evaluate_bash(policy.DEFAULT, command).kind, command)
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "git push --force-with-lease").kind)

    def test_a_recursive_delete_of_the_home_or_root_folder_is_always_denied(self):
        for command in ("rm -rf /", "rm -rf /*", "rm -rf ~/", "rm -r -f /", "rm -rf $HOME/", "rm -Rf ~", "rm --recursive /"):
            self.assertEqual("deny", policy.evaluate_bash(policy.DEFAULT, command).kind, command)

    def test_deleting_a_folder_asks_and_a_single_file_does_not(self):
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "rm -rf node_modules").kind)
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "rm -rf ~/Documents").kind)
        self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, "rm notes.txt"))

    def test_a_push_asks(self):
        self.assertEqual(("ask", "triggers.push"), tuple(getattr(policy.evaluate_bash(policy.DEFAULT, "git push"), a) for a in ("kind", "rule")))

    def test_a_push_through_git_dash_C_still_asks(self):
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "git -C /tmp/x push origin main").kind)

    def test_deleting_more_than_ten_files_asks_and_ten_does_not(self):
        self.assertEqual("ask", policy.evaluate_bash(policy.DEFAULT, "rm " + " ".join(f"f{i}" for i in range(11))).kind)
        self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, "rm " + " ".join(f"f{i}" for i in range(10))))

    def test_a_denied_path_is_refused_at_any_depth_and_an_ordinary_one_passes(self):
        root = Path("/repo")
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/.githooks/pre-commit").kind)
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/.env").kind)
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/config/.env").kind)
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, "/repo/apps/api/.secrets/key").kind)
        self.assertIsNone(policy.evaluate_path(policy.DEFAULT, root, "/repo/src/a.py"))

    def test_a_symlink_to_a_denied_file_is_refused(self):
        root = temp_dir(self, resolve=True)
        (root / ".env").write_text("A=1\n")
        (root / "notes.txt").symlink_to(root / ".env")
        self.assertEqual("deny", policy.evaluate_path(policy.DEFAULT, root, str(root / "notes.txt")).kind)

    def test_bash_cannot_write_a_denied_path_but_may_write_others(self):
        root = Path("/repo")
        for command in ("echo x > .githooks/pre-commit", "echo x >> .env", "tee config/.env", "cp a.txt .secrets/key",
                        "sed -i s/a/b/ .githooks/pre-commit", "dd if=a of=.env", "rm .env", "echo x>.env"):
            d = policy.evaluate_bash(policy.DEFAULT, command, "", root)
            self.assertEqual("deny", d and d.kind, command)
        for command in ("echo x > notes.txt", "cat .env", "grep a .githooks/pre-commit", "cp .env /tmp/backup"):
            self.assertIsNone(policy.evaluate_bash(policy.DEFAULT, command, "", root), command)

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
        (self.repo / policy.POLICY_FILE).parent.mkdir(exist_ok=True)
        (self.repo / policy.POLICY_FILE).write_text(json.dumps(ALLOW_GIT))
        out = run_guard(self.repo, {"command": "zzz now"}, self.log)
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("commands.allow", out["permissionDecisionReason"])
        self.assertIn("\tapp\tpolicy\tdeny commands.allow", self.log.read_text())

    def test_a_bash_write_to_a_denied_path_is_blocked(self):
        policy.write_default(self.repo)
        out = run_guard(self.repo, {"command": "echo x > .githooks/pre-commit"}, self.log)
        self.assertEqual("deny", out["permissionDecision"])

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
