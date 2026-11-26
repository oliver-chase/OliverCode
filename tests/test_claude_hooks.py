"""Tests for the Claude Code hooks in scripts/hooks/ and their settings merge.

These guard the fail-open one level above git: a repo that ships commit gates while git is
not pointed at them, and a commit that skips the gates on purpose. Each case runs against a
real temporary git repo.
"""

import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import claude_settings  # noqa: E402
from lib import placement  # noqa: E402

guard = load_script("scripts/hooks/commit_guard.py")
session = load_script("scripts/hooks/session_check.py")


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-claudehooks-", resolve=True)
        self.repo = scratch_repo(self.tmp / "repo")

    def gates(self, point_git_at_them: bool):
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        pre = hooks / "pre-commit"
        pre.write_text("#!/bin/sh\nexit 0\n")
        pre.chmod(pre.stat().st_mode | stat.S_IXUSR)
        if point_git_at_them:
            git(self.repo, "config", "core.hooksPath", ".githooks")


class TestSessionDigest(RepoCase):
    LINES = ["o/r: 3 open stories.", "Last story landed: #5 Done.", "Read /h/status-digest.md before acting."]

    def digest(self, env=None):
        with mock.patch.dict(os.environ, env or {}), mock.patch("lib.cmd_status.write_digest", return_value=(Path("/h/x"), "t", self.LINES)) as write:
            return session.digest_notes(self.repo), write

    def test_a_governed_repo_gets_the_three_lines(self):
        self.gates(point_git_at_them=True)
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        found, write = self.digest()
        self.assertEqual(self.LINES, found)
        write.assert_called_once()

    def test_a_headless_builder_gets_none_and_refreshes_nothing(self):
        self.gates(point_git_at_them=True)
        found, write = self.digest({"OLIVERCODE_HEADLESS": "1"})
        self.assertEqual([], found)
        write.assert_not_called()

    def test_a_repo_without_gates_gets_none(self):
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        found, write = self.digest()
        self.assertEqual([], found)
        write.assert_not_called()


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
        "nice git commit --no-verify -m x", "nice -n 5 git commit -n -m x", "timeout 10 git commit --no-verify -m x",
        "sudo -u root git commit -n -m x", "env -i nice timeout 9 git commit --no-verify -m x",
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
        "/usr/bin/git commit -n -m x", "echo `git commit -n -m x`",
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
        "GIT_CONFIG_GLOBAL=/tmp/hooks.cfg git commit -m x",
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

    def test_each_skip_refusal_is_one_line_under_200_characters_and_names_the_gates_doc(self):
        self.gates(point_git_at_them=True)
        for why in (guard.reason("git commit --no-verify -m x", self.repo), guard.reason("git -c core.hooksPath=/dev/null commit -m x", self.repo)):
            self.assertTrue(why)
            self.assertLessEqual(len(why), 200, why)
            self.assertIn("docs/GATES.md", why)

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
        text = " ".join(session.notes(self.repo, self.claude))
        self.assertIn("Commits are refused", text)
        self.assertIn("the gates are not running", text)
        self.assertIn("olivercode sync-hooks", text)
        self.assertIn("core.hooksPath is unset", text)
        self.assertIn("config core.hooksPath .githooks", text)
        git(self.repo, "config", "core.hooksPath", ".git/hooks")  # set, but not to the repo's gates
        text = " ".join(session.notes(self.repo, self.claude))
        self.assertIn("never run", text)
        self.assertIn("config core.hooksPath .githooks", text)

    def test_names_a_repo_with_no_gates(self):
        self.assertIn("no commit gates", " ".join(session.notes(self.repo, self.claude)))

    def test_a_headless_start_runs_no_placement_scan(self):
        self.addCleanup(setattr, session, "checkout_notes", session.checkout_notes)
        session.checkout_notes = lambda: []  # the checkout under test trails origin/main whenever main moves
        with mock.patch.object(placement, "findings", return_value=[]) as scan, mock.patch.dict(os.environ, {"OLIVERCODE_HEADLESS": "1"}):
            session.notes(self.tmp, self.claude)
        scan.assert_not_called()
        with mock.patch.object(placement, "findings", return_value=[]) as scan, mock.patch.dict(os.environ, {"OLIVERCODE_HEADLESS": ""}):
            session.notes(self.tmp, self.claude)
        scan.assert_called_once()

    def test_says_nothing_when_all_is_well(self):
        self.gates(point_git_at_them=True)
        self.addCleanup(setattr, session, "placement_notes", session.placement_notes)
        session.placement_notes = lambda: []  # this machine's own repos are not the subject here
        self.addCleanup(setattr, session, "checkout_notes", session.checkout_notes)
        session.checkout_notes = lambda: []  # the checkout under test is this worktree, which trails origin/main whenever main moves
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
        self.assertEqual((merged["model"], merged["permissions"]["deny"]), ("opus", self.OWNER["permissions"]["deny"]))
        self.assertEqual(merged["permissions"]["allow"], list(claude_settings.ALLOW))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertIn("~/mine.sh", commands)
        for _, _, script in claude_settings.MANAGED:
            self.assertEqual(sum(script in c for c in commands), 1, script)

    def test_allow_entries_keep_the_owners_and_health_names_a_missing_one(self):
        owner = {"permissions": {"allow": ["Bash(ls)", claude_settings.ALLOW[0]]}}
        allow = claude_settings.merge(owner)["permissions"]["allow"]
        self.assertEqual(allow, ["Bash(ls)", *claude_settings.ALLOW])
        path = temp_dir(self, "olivercode-settings-") / "settings.json"
        path.write_text(json.dumps(owner))
        self.assertEqual(claude_settings.missing_allow(path), list(claude_settings.ALLOW[1:]))
        claude_settings.install(path)
        self.assertEqual(claude_settings.missing_allow(path), [])
        for rule in ("mcp__ccd_sidebar__set_pinned", "mcp__ccd_session__start_session", "Bash(olivercode clean*)"):
            self.assertIn(rule, claude_settings.ALLOW)
        for rule in ("Bash(git worktree remove *)", "Bash(git -C * worktree remove *)", "Bash(bash scripts/validate.sh*)"):
            self.assertNotIn(rule, claude_settings.ALLOW)
        old = {"permissions": {"allow": ["Bash(ls)", "Bash(git worktree remove *)", "Bash(bash scripts/validate.sh*)"]}}
        self.assertEqual(claude_settings.merge(old)["permissions"]["allow"], ["Bash(ls)", *claude_settings.ALLOW])

    def test_show_allow_names_each_rule_with_what_it_permits(self):
        path = temp_dir(self, "olivercode-settings-") / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": [claude_settings.ALLOW[0]]}}))
        lines = claude_settings.allow_lines(path)
        self.assertEqual(len(lines), len(claude_settings.ALLOW))
        self.assertIn("[PRESENT]", lines[0])
        self.assertTrue(all("[WILL ADD]" in line for line in lines[1:]))
        self.assertEqual(set(claude_settings.ALLOW_WHY), set(claude_settings.ALLOW))
        path.write_text("{}")
        self.assertTrue(all("[WILL ADD]" in line for line in claude_settings.allow_lines(path)))

    def test_reinstalling_or_moving_the_checkout_never_duplicates(self):
        once = claude_settings.merge(self.OWNER, Path("/old/place/scripts/hooks"))
        moved = claude_settings.merge(once, Path("/new/place/scripts/hooks"))
        commands = [h["command"] for groups in moved["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertFalse([c for c in commands if "/old/place/" in c])
        self.assertEqual(claude_settings.merge(moved, Path("/new/place/scripts/hooks")), moved)

    def test_a_settings_shape_the_merge_would_guess_at_is_refused_and_left_alone(self):
        tmp = temp_dir(self, "olivercode-settings-")
        path = tmp / "settings.json"
        for bad in ({"hooks": None}, {"hooks": []}, {"hooks": {"Stop": ["a string"]}}, ["not", "an", "object"]):
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                claude_settings.install(path)
            self.assertEqual(json.loads(path.read_text()), bad)

    def test_install_writes_once_and_then_reports_already(self):
        tmp = temp_dir(self, "olivercode-settings-")
        path = tmp / "settings.json"
        path.write_text(json.dumps(self.OWNER))
        self.assertEqual(claude_settings.install(path), "updated")
        self.assertEqual(claude_settings.install(path), "already")
        self.assertEqual(json.loads(path.read_text())["model"], "opus")


class TestSettingsRemove(unittest.TestCase):
    OWNER = TestSettingsMerge.OWNER

    def setUp(self):
        tmp = temp_dir(self, "olivercode-settings-")
        self.path = tmp / "settings.json"

    def test_install_then_remove_gives_back_the_owners_settings(self):
        self.path.write_text(json.dumps(self.OWNER))
        claude_settings.install(self.path, Path("/oc/scripts/hooks"))
        self.assertEqual(claude_settings.remove(self.path), "removed")
        self.assertEqual(json.loads(self.path.read_text()), self.OWNER)

    def test_an_owner_hook_sharing_a_group_with_oliver_codes_stays(self):
        mine = {"type": "command", "command": "~/mine.sh"}
        ours = {"type": "command", "command": 'python3 "/oc/scripts/hooks/pretool_guard.py"'}
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine, ours]}]}}
        self.assertEqual(claude_settings.without(settings),
                         {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine]}]}})

    def test_install_removes_the_retired_manager_entries_from_any_checkout(self):
        retired = [{"type": "command", "command": f'python3 "/old/checkout/scripts/hooks/{n}"'} for n in claude_settings.RETIRED]
        mine = {"type": "command", "command": "~/mine.sh"}
        settings = {"hooks": {"PreToolUse": [{"hooks": retired}, {"matcher": "Bash", "hooks": [mine]}],
                              "UserPromptSubmit": [{"hooks": [retired[3]]}]}}
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        for name in claude_settings.RETIRED:
            self.assertFalse(any(name in c for c in commands), name)
        self.assertIn("~/mine.sh", commands)
        self.assertFalse({n for _, _, n in claude_settings.MANAGED} & set(claude_settings.RETIRED))

    def test_install_drops_the_denial_watch_entry_and_leaves_its_script(self):
        entry = {"type": "command", "command": 'python3 "/old/checkout/scripts/hooks/denial_watch.py"'}
        merged = claude_settings.merge({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [entry]}]}}, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertFalse(any("denial_watch" in c for c in commands))
        self.assertNotIn("denial_watch.py", [n for _, _, n in claude_settings.MANAGED])
        self.assertTrue((claude_settings.HOOKS_DIR / "denial_watch.py").is_file())

    def test_dead_names_a_managed_entry_whose_script_does_not_exist(self):
        root = temp_dir(self, "olivercode-dead-", resolve=True)
        (root / "scripts" / "hooks").mkdir(parents=True)
        (root / "scripts" / "hooks" / "here.py").write_text("")
        cmds = [f'python3 "{root}/scripts/hooks/{n}"' for n in ("session_check.py", "gh_watch.py")]
        path = root / "settings.json"
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c}]} for c in cmds]}}))
        self.assertEqual(claude_settings.dead(path), cmds)
        (root / "scripts" / "hooks" / "gh_watch.py").write_text("")
        self.assertEqual(claude_settings.dead(path), cmds[:1])
        self.assertEqual(claude_settings.dead(root / "absent.json"), [])

    def test_a_reinstall_removes_a_cut_hook(self):
        cut = {"type": "command", "command": 'python3 "/oc/scripts/hooks/trace_watch.py"'}
        settings = {"hooks": {"PostToolUse": [{"hooks": [cut]}]}}
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertNotIn(cut["command"], commands)

    def test_install_drops_an_entry_whose_script_is_gone_and_keeps_the_rest(self):
        hooks_dir = temp_dir(self, "olivercode-hooksdir-", resolve=True)
        (hooks_dir / "still_here.py").write_text("")
        gone = {"type": "command", "command": f'python3 "{hooks_dir}/gone.py"'}
        kept = [{"type": "command", "command": c} for c in (
            f'python3 "{hooks_dir}/still_here.py"',  # the script exists, so it stays
            'python3 "/elsewhere/scripts/hooks/gone.py"',  # another checkout's folder
            f'python3 "{hooks_dir}/gone.py" --flag',  # not the form install writes
            "~/mine.sh")]
        settings = {"hooks": {"PostToolUse": [{"hooks": [gone]}, {"matcher": "Bash", "hooks": [gone, *kept]}]}}
        merged = claude_settings.merge(settings, hooks_dir)
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertNotIn(gone["command"], commands)
        self.assertTrue(all(h["command"] in commands for h in kept))
        self.assertEqual(merged["hooks"]["PostToolUse"][0], {"matcher": "Bash", "hooks": kept})

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


hint = load_script("scripts/hooks/status_hint.py")
DIGEST = """# Status digest
Written 2026-11-23 13:00 UTC.
Board: owner/repo: 3 open stories.

## Open, 2 in priority order
- #991 P1 The guide teaches efficient use
- #979 P1 Stories build one at a time

## Landed, the last five
- #985 A new thread starts from the digest

## Waits on the owner
Nothing.
"""


class StatusHint(unittest.TestCase):
    """#991: a status question is answered from the digest with no tool call, and any other message gets nothing."""

    def setUp(self):
        self.tmp = temp_dir(self)
        self.digest = self.tmp / "status-digest.md"
        self.digest.write_text(DIGEST, encoding="utf-8")

    def test_a_status_question_gets_the_board_and_open_lines_with_the_path_and_no_landed_section(self):
        for prompt in ("what's building right now?", "what is left on the board", "when will it finish?", "any status on the queue",
                       "what's the status?", "status of the queue", "status?"):
            text = hint.context(prompt, self.digest)
            self.assertIn("Board: owner/repo: 3 open stories.", text, prompt)
            self.assertIn("#991 P1", text, prompt)
            self.assertIn(str(self.digest), text, prompt)
            self.assertIn("no tool call", text, prompt)
            self.assertNotIn("## Landed", text, prompt)

    def test_any_other_message_gets_nothing(self):
        for prompt in ("fix the parser bug in cmd_land", "what does the status code in cmd_land do", "", "Add a status field to the story schema",
                       "fix the status handling in cmd_land", "the PR status is red", "when the hook is ready to commit, fix the parser"):
            self.assertEqual("", hint.context(prompt, self.digest), prompt)

    def test_a_message_from_another_session_gets_nothing(self):
        prompt = "Another Claude session sent a message: what is building?"
        self.assertEqual("", hint.context(prompt, self.digest))

    def test_a_missing_digest_is_said_and_no_tool_call_is_implied(self):
        text = hint.context("what's left?", self.tmp / "absent.md")
        self.assertIn("No status digest is written yet", text)
        self.assertIn("olivercode status digest", text)

    def test_the_hook_adds_context_only_for_a_status_question_and_fails_open_on_bad_input(self):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        env = dict(os.environ, OLIVERCODE_HOME=str(self.tmp))
        (self.tmp / "status-digest.md").write_text(DIGEST, encoding="utf-8")
        status = subprocess.run([sys.executable, script], input='{"prompt": "what is building?"}', capture_output=True, text=True, env=env)
        self.assertEqual(0, status.returncode)
        self.assertIn("additionalContext", status.stdout)
        other = subprocess.run([sys.executable, script], input='{"prompt": "fix the parser bug"}', capture_output=True, text=True, env=env)
        self.assertEqual((0, ""), (other.returncode, other.stdout))
        bad = subprocess.run([sys.executable, script], input="not json", capture_output=True, text=True, env=env)
        self.assertEqual(0, bad.returncode)


class TestRetiredDesignHook(unittest.TestCase):
    """A settings file written by a later install can name design_hook.py, so the script stays as a no-op that install strips."""

    def test_the_script_exits_0_and_prints_nothing(self):
        script = str(REPO_ROOT / "scripts" / "hooks" / "design_hook.py")
        ran = subprocess.run([sys.executable, script], input='{"tool_name": "Edit"}', capture_output=True, text=True)
        self.assertEqual((0, "", ""), (ran.returncode, ran.stdout, ran.stderr))

    def test_install_strips_its_entry(self):
        self.assertIn("design_hook.py", claude_settings.RETIRED)
