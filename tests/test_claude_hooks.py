"""Tests for the Claude Code hooks in scripts/hooks/ and their settings merge.

These guard the fail-open one level above git: a repo that ships commit gates while git is
not pointed at them, and a commit that skips the gates on purpose. Each case runs against a
real temporary git repo.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, load_script, scratch_repo

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import claude_settings  # noqa: E402

guard = load_script("scripts/hooks/commit_guard.py")
session = load_script("scripts/hooks/session_check.py")


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-claudehooks-")).resolve()
        self.repo = self.tmp / "repo"
        scratch_repo(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gates(self, point_git_at_them: bool):
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        pre = hooks / "pre-commit"
        pre.write_text("#!/bin/sh\nexit 0\n")
        pre.chmod(pre.stat().st_mode | stat.S_IXUSR)
        if point_git_at_them:
            git(self.repo, "config", "core.hooksPath", ".githooks")


class TestCommitGuard(RepoCase):
    def test_refuses_a_commit_when_the_repo_has_gates_and_git_skips_them(self):
        self.gates(point_git_at_them=False)
        self.assertIn("core.hooksPath is unset", guard.reason('git commit -m "x"', self.repo))
        self.assertIn("core.hooksPath is unset", guard.reason(f'cd "{self.repo}" && git commit -m x', self.tmp))
        self.assertIn("core.hooksPath is unset", guard.reason(f'git -C "{self.repo}" commit -m x', self.tmp))

    def test_allows_a_commit_when_the_gates_run(self):
        self.gates(point_git_at_them=True)
        self.assertEqual(guard.reason('git add . && git commit -m "x"', self.repo), "")

    # Every way a session has tried to skip or redirect the gates, each refused in a repo whose gates run.
    SKIPS = (
        "git commit --no-verify -m x", "git commit -n -m x", "git commit -nm x", "git commit -anm x",
        "git commit --no-verif -m x", "git commit --no-ver -m x", "git commit --no-v -m x",  # any prefix git accepts
        'git commit -m "a; b" --no-verify', "git commit -m 'x | y' -n",
        "git commit --no-verify -m \"$(cat <<'EOF'\nsubject; body | more && done\nEOF\n)\"",
        "git add .\ngit commit --no-verify -m x", "(git commit --no-verify -m x)", "env git commit --no-verify -m x",
        "true & git commit --no-verify -m x", "command git commit -n -m x", "FOO=1 git commit --no-verify -m x",
        "A=1 B=2 git commit -n -m x", "git add -A; git commit --no-verify -m x", "git add -A ;git commit -n -m x",
        "echo msg | git commit --no-verify -F -", "true || git commit -n -m x",
        'bash -c "git commit --no-verify -m x"', "sh -c 'git commit -n -m x'", 'eval "git commit --no-verify -m x"',
        "git --namespace ns commit -n -m x",
        "git -c alias.ci='commit -n' ci -m x", 'git -c "alias.ci=commit --no-verify" ci -m x',
        "git -c alias.ci='commit -m y' ci -n", "git -c alias.CI='commit -n' ci -m x",
        "git -c Alias.CI='commit -n' ci -m x", "git -c alias.ci='!git commit -n' CI -m x",
        "git -c alias.ci='!f() { git commit -n -m x; }; f' ci", "git -c alias.a=ci -c alias.ci='commit -n' a -m x",
        "git -c alias.ci='!git ci2' -c alias.ci2='commit -n' ci -m x",
        "git " + " ".join(f"-c alias.a{k}=a{k + 1}" for k in range(8)) + " -c alias.a8='commit -n' a0 -m x",
        "git " + " ".join(f"-c alias.a{k}='!git a{k + 1}'" for k in range(8)) + " -c alias.a8='commit -n' a0",
        "git -c alias.ci='!f() { git commit \"$@\"; }; f' ci -n -m x", "git -c alias.ci='!f() { git $1 -n -m x; }; f' ci commit",
        "git -c alias.ci='!f() { git commit ${1} -m x; }; f' ci -n",
        "git -c alias.ci='!f() { git commit \"${@}\"; }; f' ci -n -m x",
        "git -c alias.ci='!git -c alias.ci=\"commit -n\" ci' ci -m x", "V='commit -n' git --config-env=alias.ci=V ci -m x",
    )
    OVERRIDES = (
        "git -c core.hooksPath=/dev/null commit -m x", "git -ccore.hooksPath=/dev/null commit -m x",
        "git --config-env=core.hooksPath=X commit -m x",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
        "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null; git commit -m x",
        "GIT_CONFIG_PARAMETERS='core.hookspath=/dev/null' git commit -m x",
        "git config core.hooksPath /dev/null && git commit -m x", "git config --local core.hookspath /dev/null; git commit -m x",
        "git config --unset core.hooksPath && git commit -m x",
        "git -c alias.ci='-c core.hooksPath=/dev/null commit' ci -m x",
    )
    ALLOWED = (
        "git commit --no-edit -m x", "git commit --no-verify=1 -m x",  # git rejects a value on --no-verify
        "git -c alias.ci=commit ci -m x", "git -c alias.a=b -c alias.b=a a",  # a loop git refuses
        "git config core.hooksPath .githooks && git commit -m x",  # the fix the refusal recommends
        "git config --local core.hooksPath ./.githooks; git commit -m x", "git config core.hooksPath && git commit -m x",
        "git commit -m -n", "git commit -mnote", "git commit -F notes.txt", 'echo "git commit -n" > notes.txt',
        "git commit -uno -m x", "git commit -Snewkey -m x", "git commit -auno -m x", 'bash -c "git commit -m x"',
    )

    def test_every_skip_and_override_is_refused_and_ordinary_commits_pass(self):
        self.gates(point_git_at_them=True)
        for cmd in self.SKIPS:
            self.assertIn("skips the repo's commit gates", guard.reason(cmd, self.repo), repr(cmd))
        for cmd in self.OVERRIDES:
            self.assertIn("overrides core.hooksPath", guard.reason(cmd, self.repo), repr(cmd))
        for cmd in self.ALLOWED:
            self.assertEqual(guard.reason(cmd, self.repo), "", repr(cmd))
        for cmd in (f'git --git-dir "{self.repo}/.git" commit -n -m x', f'git --work-tree "{self.repo}" commit -n -m x',
                    f'git --git-dir="{self.repo}/.git" commit -n -m x', f'git --work-tree="{self.repo}" commit -n -m x',
                    f'GIT_DIR="{self.repo}/.git" git commit -n -m x', f'export GIT_DIR="{self.repo}/.git"; git commit -n -m x'):
            self.assertIn("--no-verify", guard.reason(cmd, self.tmp), cmd)  # the guard follows the command to the repo

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
        git(self.repo, "config", "core.hooksPath", ".git/hooks")
        self.assertIn(".githooks", guard.reason('git commit -m "x"', self.repo))

    def test_skipping_hooks_in_a_repo_with_no_gates_skips_nothing_and_is_allowed(self):
        self.assertEqual(guard.reason("git commit --no-verify -m x", self.repo), "")

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

    def test_machine_strain_names_a_runaway_test_runner_and_high_load(self):
        ps = "  71592  99.3 22:54:46 node (vitest 1)\n  100  2.0 22:54:46 node server\n  200  90.0 00:10:00 node (vitest 2)"
        found = session.machine_strain(ps, 2.0, 8)
        self.assertEqual(len(found), 1)
        self.assertIn("pid 71592", found[0])
        self.assertIn("kill 71592", found[0])
        self.assertIn("load is 13.0 on 8 cores", " ".join(session.machine_strain("", 13.0, 8)))
        self.assertEqual(session.machine_strain("", 4.0, 8), [])
        self.assertEqual(session._hours("1-02:00:00"), 26.0)

    def test_stories_waiting_in_qa_are_named_and_a_missing_config_or_gh_stays_silent(self):
        self.assertEqual(session.qa_queue(self.repo), "")  # no backlog config
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps({"projectNumber": 5, "projectOwner": "o"}))
        items = {"items": [{"status": "QA", "content": {"number": 7}}, {"status": "Complete", "content": {"number": 8}},
                           {"status": "QA", "content": {"number": 3}}]}
        run = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(items), "")  # noqa: E731
        self.assertIn("2 stories waiting in QA (#3, #7)", session.qa_queue(self.repo, run))
        def no_gh(*a, **k):
            raise FileNotFoundError("gh")
        self.assertEqual(session.qa_queue(self.repo, no_gh), "")


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


class TestSettingsRemove(unittest.TestCase):
    OWNER = TestSettingsMerge.OWNER

    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-settings-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.path = tmp / "settings.json"

    def test_install_then_remove_gives_back_the_owners_settings(self):
        self.path.write_text(json.dumps(self.OWNER))
        claude_settings.install(self.path, Path("/oc/scripts/hooks"))
        self.assertEqual(claude_settings.remove(self.path), "removed")
        self.assertEqual(json.loads(self.path.read_text()), self.OWNER)

    def test_an_owner_hook_sharing_a_group_with_oliver_codes_stays(self):
        mine = {"type": "command", "command": "~/mine.sh"}
        ours = {"type": "command", "command": 'python3 "/oc/scripts/hooks/commit_guard.py"'}
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine, ours]}]}}
        self.assertEqual(claude_settings.without(settings),
                         {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine]}]}})

    def test_a_file_with_none_of_oliver_codes_hooks_is_not_rewritten(self):
        text = '{"model":"opus","hooks":{}}'
        self.path.write_text(text)
        self.assertEqual(claude_settings.remove(self.path), "absent")
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(claude_settings.remove(self.path.with_name("missing.json")), "absent")

    def test_an_owner_hook_that_runs_a_script_of_the_same_name_is_never_touched(self):
        owners = ["python3 ~/work/myrepo/scripts/hooks/session_check.py",
                  "/opt/x/scripts/hooks/my_commit_guard.py --strict",
                  "bash -c 'log; python3 /oc/scripts/hooks/early-stop-guard.py'",
                  'python3 "/oc/scripts/hooks/commit_guard.py" --extra']
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c}]} for c in owners]}}
        self.assertEqual(claude_settings.without(settings), settings)
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
        self.assertTrue(all(c in commands for c in owners))

    def test_a_moved_checkouts_entries_are_still_recognised(self):
        settings = claude_settings.merge({}, Path("/old place/scripts/hooks"))
        self.assertEqual(claude_settings.without(settings), {})

    def test_a_symlinked_private_settings_file_stays_a_private_link(self):
        real = self.path.with_name("dotfiles-settings.json")
        real.write_text(json.dumps(self.OWNER))
        real.chmod(0o600)
        self.path.symlink_to(real)
        claude_settings.install(self.path, Path("/oc/scripts/hooks"))
        self.assertTrue(self.path.is_symlink(), "install replaced the link with a plain file")
        self.assertEqual(oct(real.stat().st_mode & 0o777), oct(0o600))
        self.assertEqual(claude_settings.remove(self.path), "removed")
        self.assertTrue(self.path.is_symlink(), "remove replaced the link with a plain file")
        self.assertEqual(oct(real.stat().st_mode & 0o777), oct(0o600))
        self.assertEqual(json.loads(real.read_text()), self.OWNER)

    def test_a_file_only_oliver_code_filled_is_deleted_unless_it_is_a_link(self):
        claude_settings.install(self.path, Path("/oc/scripts/hooks"))
        self.assertEqual(claude_settings.remove(self.path), "deleted")
        self.assertFalse(self.path.exists())
        real = self.path.with_name("dotfiles-settings.json")
        self.path.symlink_to(real)
        claude_settings.install(self.path, Path("/oc/scripts/hooks"))
        self.assertEqual(claude_settings.remove(self.path), "removed")
        self.assertEqual(json.loads(real.read_text()), {})

    def test_a_settings_shape_it_would_guess_at_is_refused_and_left_alone(self):
        for bad in ({"hooks": None}, {"hooks": {"Stop": ["a string"]}}, ["not", "an", "object"]):
            self.path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                claude_settings.remove(self.path)
            self.assertEqual(json.loads(self.path.read_text()), bad)


if __name__ == "__main__":
    unittest.main()
