"""Tests for the Claude Code hooks in scripts/hooks/ and their settings merge.

These guard the fail-open one level above git: a repo that ships commit gates while git is
not pointed at them, and a commit that skips the gates on purpose. Each case runs against a
real temporary git repo.
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import claude_settings  # noqa: E402


def _load(name: str):
    path = REPO_ROOT / "scripts" / "hooks" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load("commit_guard.py")
session = _load("session_check.py")


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-claudehooks-")).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gates(self, point_git_at_them: bool):
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        pre = hooks / "pre-commit"
        pre.write_text("#!/bin/sh\nexit 0\n")
        pre.chmod(pre.stat().st_mode | stat.S_IXUSR)
        if point_git_at_them:
            subprocess.run(["git", "-C", str(self.repo), "config", "core.hooksPath", ".githooks"], check=True)


class TestCommitGuard(RepoCase):
    def test_refuses_a_commit_when_the_repo_has_gates_and_git_skips_them(self):
        self.gates(point_git_at_them=False)
        self.assertIn("core.hooksPath is unset", guard.reason('git commit -m "x"', self.repo))
        self.assertIn("core.hooksPath is unset", guard.reason(f'cd "{self.repo}" && git commit -m x', self.tmp))
        self.assertIn("core.hooksPath is unset", guard.reason(f'git -C "{self.repo}" commit -m x', self.tmp))

    def test_allows_a_commit_when_the_gates_run(self):
        self.gates(point_git_at_them=True)
        self.assertEqual(guard.reason('git add . && git commit -m "x"', self.repo), "")

    def test_allows_a_commit_in_a_repo_with_no_gates(self):
        self.assertEqual(guard.reason('git commit -m "x"', self.repo), "")

    def test_refuses_skipping_the_gates_on_purpose(self):
        self.gates(point_git_at_them=True)
        for cmd in ('git commit --no-verify -m x', 'git commit -n -m x', 'git commit -nm x', 'git commit -anm x'):
            self.assertIn("--no-verify", guard.reason(cmd, self.repo), cmd)
        self.assertIn("overrides core.hooksPath", guard.reason("git -c core.hooksPath=/dev/null commit -m x", self.repo))

    def test_separators_inside_a_message_do_not_hide_the_commit(self):
        self.gates(point_git_at_them=True)
        heredoc = "git commit --no-verify -m \"$(cat <<'EOF'\nsubject; body | more && done\nEOF\n)\""
        for cmd in ('git commit -m "a; b" --no-verify', "git commit -m 'x | y' -n", heredoc):
            self.assertIn("--no-verify", guard.reason(cmd, self.repo), cmd)

    def test_newlines_subshells_and_wrappers_do_not_hide_the_commit(self):
        self.gates(point_git_at_them=True)
        for cmd in ("git add .\ngit commit --no-verify -m x", "(git commit --no-verify -m x)",
                    "env git commit --no-verify -m x", "true & git commit --no-verify -m x",
                    "command git commit -n -m x"):
            self.assertIn("--no-verify", guard.reason(cmd, self.repo), repr(cmd))

    def test_a_leading_variable_assignment_does_not_hide_the_commit(self):
        self.gates(point_git_at_them=True)
        for cmd in ("FOO=1 git commit --no-verify -m x", "A=1 B=2 git commit -n -m x"):
            self.assertIn("--no-verify", guard.reason(cmd, self.repo), cmd)

    def test_a_semicolon_or_pipe_before_the_commit_does_not_hide_it(self):
        self.gates(point_git_at_them=True)
        for cmd in ("git add -A; git commit --no-verify -m x", "git add -A ;git commit -n -m x",
                    "echo msg | git commit --no-verify -F -", "true || git commit -n -m x"):
            self.assertIn("--no-verify", guard.reason(cmd, self.repo), cmd)

    def test_every_way_of_overriding_core_hookspath_is_refused(self):
        self.gates(point_git_at_them=True)
        for cmd in ("git -ccore.hooksPath=/dev/null commit -m x", "git --config-env=core.hooksPath=X commit -m x",
                    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x"):
            self.assertIn("overrides core.hooksPath", guard.reason(cmd, self.repo), cmd)

    def test_a_message_with_separators_still_reaches_the_unset_hooks_check(self):
        self.gates(point_git_at_them=False)
        for cmd in ('git commit -am "msg; with semicolon"', 'git commit -m "a && b"'):
            self.assertIn("core.hooksPath is unset", guard.reason(cmd, self.repo), cmd)

    def test_git_pointed_at_another_hooks_folder_does_not_run_the_repos_gates(self):
        self.gates(point_git_at_them=False)
        other = self.repo / ".git" / "hooks"
        other.mkdir(parents=True, exist_ok=True)
        stub = other / "pre-commit"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        subprocess.run(["git", "-C", str(self.repo), "config", "core.hooksPath", ".git/hooks"], check=True)
        self.assertIn(".githooks", guard.reason('git commit -m "x"', self.repo))

    def test_a_message_or_value_that_looks_like_n_is_not_a_skip(self):
        self.gates(point_git_at_them=True)
        for cmd in ('git commit -m -n', 'git commit -mnote', 'git commit -F notes.txt', 'echo "git commit -n" > notes.txt'):
            self.assertEqual(guard.reason(cmd, self.repo), "", cmd)

    def test_the_hook_prints_a_deny_decision(self):
        self.gates(point_git_at_them=False)
        out = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "hooks" / "commit_guard.py")],
                             input=json.dumps({"cwd": str(self.repo), "tool_input": {"command": "git commit -m x"}}),
                             capture_output=True, text=True)
        decision = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual((out.returncode, decision["permissionDecision"]), (0, "deny"))

    def test_bad_input_fails_open(self):
        out = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "hooks" / "commit_guard.py")],
                             input="not json", capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, ""))


class TestSessionCheck(RepoCase):
    def setUp(self):
        super().setUp()
        self.claude = self.tmp / "claude"
        self.claude.mkdir()

    def test_names_gates_that_git_skips(self):
        self.gates(point_git_at_them=False)
        self.assertIn("Commits are refused", " ".join(session.notes(self.repo, self.claude)))

    def test_names_a_repo_with_no_gates(self):
        self.assertIn("no commit gates", " ".join(session.notes(self.repo, self.claude)))

    def test_says_nothing_when_all_is_well(self):
        self.gates(point_git_at_them=True)
        self.assertEqual(session.notes(self.repo, self.claude), [])
        self.assertEqual(session.notes(self.tmp, self.claude), [])  # not a git repo

    def test_names_a_broken_rules_link(self):
        os.symlink(self.tmp / "gone.md", self.claude / "CLAUDE.md")
        self.assertIn("broken link", " ".join(session.notes(self.tmp, self.claude)))


class TestSettingsMerge(unittest.TestCase):
    OWNER = {"model": "opus", "permissions": {"deny": ["Bash(rm -rf *)"]},
             "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "~/mine.sh"}]}]}}

    def test_adds_its_hooks_and_keeps_everything_of_the_owners(self):
        merged = claude_settings.merge(self.OWNER, Path("/oc/scripts/hooks"))
        self.assertEqual((merged["model"], merged["permissions"]), ("opus", self.OWNER["permissions"]))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertIn("~/mine.sh", commands)
        for _, _, script in claude_settings.MANAGED:
            self.assertEqual(sum(script in c for c in commands), 1, script)

    def test_reinstalling_or_moving_the_checkout_never_duplicates(self):
        once = claude_settings.merge(self.OWNER, Path("/old/place/scripts/hooks"))
        moved = claude_settings.merge(once, Path("/new/place/scripts/hooks"))
        commands = [h["command"] for groups in moved["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertFalse([c for c in commands if "/old/place/" in c])
        self.assertEqual(claude_settings.merge(moved, Path("/new/place/scripts/hooks")), moved)

    def test_a_settings_shape_the_merge_would_guess_at_is_refused_and_left_alone(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-settings-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "settings.json"
        for bad in ({"hooks": None}, {"hooks": []}, {"hooks": {"Stop": ["a string"]}}, ["not", "an", "object"]):
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                claude_settings.install(path)
            self.assertEqual(json.loads(path.read_text()), bad)

    def test_install_writes_once_and_then_reports_already(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-settings-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "settings.json"
        path.write_text(json.dumps(self.OWNER))
        self.assertEqual(claude_settings.install(path), "updated")
        self.assertEqual(claude_settings.install(path), "already")
        self.assertEqual(json.loads(path.read_text())["model"], "opus")


if __name__ == "__main__":
    unittest.main()
