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

from _support import REPO_ROOT, git, load_script, quiet, scratch_repo, temp_dir

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
    def digest(self, env=None):
        (path := self.tmp / "status-digest.md").write_text("# Status digest\nBoard: o/r: 3 open. In the last 7 days 1 closed.\n")
        self.LINES = ["o/r: 3 open stories.", "No story landing is recorded in the run log yet.", f"Read {path} before acting."]
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.tmp), **(env or {})}), mock.patch("lib.repo_state.origin", return_value="o/r"), mock.patch.object(session, "detach") as write:
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


class TestUpdateNotice(unittest.TestCase):
    """The session-start line that says the checkout trails its upstream branch (#1285)."""

    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-update-", resolve=True)
        origin = scratch_repo(self.tmp / "origin.git", bare=True, branch="main")
        self.maker = scratch_repo(self.tmp / "maker", branch="main")
        self.commit(self.maker, "base")
        git(self.maker, "push", "-q", str(origin), "main")
        git(self.tmp, "clone", "-q", str(origin), "checkout")
        self.checkout = self.tmp / "checkout"
        self.origin = origin
        self.home = self.tmp / "home"
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("OLIVERCODE_HEADLESS", None)

    def test_the_update_line_also_reaches_the_user_as_a_system_message(self):
        line = "3 OliverCode updates are available. Run `olivercode update`."
        out = session.payload(["OliverCode session check: " + line], [line])
        self.assertEqual(line, out["systemMessage"])
        self.assertIn(line, out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("systemMessage", session.payload(["OliverCode session check: other"], ["other"]))

    def commit(self, repo, name):
        (repo / name).write_text(name)
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", name)

    def push_and_fetch(self, count):
        for n in range(count):
            self.commit(self.maker, f"c{n}")
        git(self.maker, "push", "-q", str(self.origin), "main")
        git(self.checkout, "fetch", "-q")

    def test_behind_prints_one_line_with_the_count(self):
        self.push_and_fetch(3)
        self.assertEqual(session.update_notes(self.checkout), ["3 OliverCode updates are available. Run `olivercode update`."])

    def test_one_commit_behind_reads_singular(self):
        self.push_and_fetch(1)
        self.assertEqual(session.update_notes(self.checkout), ["1 OliverCode update is available. Run `olivercode update`."])

    def test_level_prints_nothing(self):
        self.assertEqual(session.update_notes(self.checkout), [])

    def test_git_failure_or_no_upstream_prints_nothing(self):
        self.assertEqual(session.update_notes(self.tmp / "missing"), [])
        git(self.checkout, "branch", "--unset-upstream")
        self.assertEqual(session.update_notes(self.checkout), [])
        with mock.patch.object(session.subprocess, "run", side_effect=OSError("no git")):
            self.assertEqual(session.update_notes(self.checkout), [])

    def test_headless_session_prints_nothing_and_fetches_nothing(self):
        self.push_and_fetch(2)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HEADLESS": "1"}), mock.patch.object(session, "start_fetch") as popen:
            self.assertEqual(session.update_notes(self.checkout), [])
        popen.assert_not_called()

    def test_stale_fetch_starts_one_background_fetch_a_day(self):
        fetch_head = self.checkout / ".git" / "FETCH_HEAD"
        fetch_head.write_text("")
        old = fetch_head.stat().st_mtime - 2 * 24 * 3600
        os.utime(fetch_head, (old, old))
        with mock.patch.object(session, "start_fetch") as popen:
            session.update_notes(self.checkout)
            session.update_notes(self.checkout)  # a second session within the day starts none
        popen.assert_called_once_with(self.checkout)
        self.assertTrue((self.home / "update-fetch-attempt").exists())

    def test_start_fetch_detaches_a_quiet_fetch(self):
        with mock.patch.object(session.subprocess, "Popen") as popen:
            session.start_fetch(self.checkout)
        self.assertEqual(popen.call_args.args[0][-2:], ["fetch", "--quiet"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_fresh_fetch_starts_none(self):
        (self.checkout / ".git" / "FETCH_HEAD").write_text("")
        with mock.patch.object(session, "start_fetch") as popen:
            session.update_notes(self.checkout)
        popen.assert_not_called()


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

    def test_the_removed_learning_hooks_are_not_written_and_an_old_install_loses_them(self):
        """#1275: lesson_capture, owner_decision_capture and error_paste are gone, and a settings file that still names them is cleaned on install."""
        removed = ("lesson_capture.py", "owner_decision_capture.py", "error_paste.py")
        self.assertFalse([s for _, _, s in claude_settings.MANAGED if s in removed])
        old = json.loads(json.dumps(self.OWNER))
        old["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": claude_settings._command(s, Path("/oc/scripts/hooks")), "timeout": 10}]} for s in removed]
        merged = claude_settings.merge(old, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        for script in removed:
            self.assertFalse([c for c in commands if script in c], script)
        self.assertIn("~/mine.sh", commands)

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

    def test_install_removes_entries_for_scripts_the_version_no_longer_ships(self):
        names = ("start_guard.py", "ask_guard.py", "context_guard.py", "never_heard_of_it.py")
        gone = [{"type": "command", "command": f'python3 "/old/olivercode/scripts/hooks/{n}"'} for n in names]
        mine = {"type": "command", "command": "~/mine.sh"}
        settings = {"hooks": {"PreToolUse": [{"hooks": gone}, {"matcher": "Bash", "hooks": [mine]}]}}
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        for name in names:
            self.assertFalse(any(name in c for c in commands), name)
        self.assertIn("~/mine.sh", commands)

    def test_an_entry_of_a_checkout_with_scripts_olivercode_goes_in_either_form(self):
        root = temp_dir(self, "olivercode-other-", resolve=True)
        (root / "scripts").mkdir()
        (root / "scripts" / "olivercode").write_text("")
        new = claude_settings._command("cut_script.py", root / "scripts" / "hooks")
        old = f'python3 "{root}/scripts/hooks/cut_script.py"'
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c}]} for c in (new, old)]}}
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertFalse(any("cut_script" in c for c in commands))

    def test_an_entry_from_an_existing_checkout_without_scripts_olivercode_is_kept(self):
        root = temp_dir(self, "olivercode-theirs-", resolve=True)
        (root / "scripts" / "hooks").mkdir(parents=True)
        theirs = [claude_settings._command("session_check.py", root / "scripts" / "hooks"),
                  f'python3 "{root}/scripts/hooks/their_hook.py"']
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c} for c in theirs]}]}}
        merged = claude_settings.merge(settings, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        for c in theirs:
            self.assertIn(c, commands)

    def test_a_script_outside_a_scripts_hooks_folder_is_never_removed(self):
        mine = [{"type": "command", "command": c} for c in (
            'python3 "/old/olivercode/scripts/other/start_guard.py"',
            'python3 "/old/olivercode/hooks/session_check.py"',
            'python3 "/old/olivercode/scripts/hooks/sub/session_check.py"',
            claude_settings._command("mine.py", Path("/home/me/bin")))]
        merged = claude_settings.merge({"hooks": {"Stop": [{"hooks": mine}]}}, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        for h in mine:
            self.assertIn(h["command"], commands)

    def test_installing_twice_leaves_one_entry_per_managed_hook(self):
        path = self.path
        hooks_dir = Path("/oc/scripts/hooks")
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": 'python3 "/gone/olivercode/scripts/hooks/cut.py"'}]}]}}))
        claude_settings.install(path, hooks_dir)
        self.assertEqual("already", claude_settings.install(path, hooks_dir))
        commands = [h["command"] for groups in json.loads(path.read_text())["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertEqual(sorted(claude_settings._command(n, hooks_dir) for _, _, n in claude_settings.MANAGED), sorted(commands))

    def test_install_drops_the_denial_watch_entry_and_leaves_its_script(self):
        entry = {"type": "command", "command": 'python3 "/old/olivercode/scripts/hooks/denial_watch.py"'}
        merged = claude_settings.merge({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [entry]}]}}, Path("/oc/scripts/hooks"))
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertFalse(any("denial_watch" in c for c in commands))
        self.assertNotIn("denial_watch.py", [n for _, _, n in claude_settings.MANAGED])
        self.assertTrue((claude_settings.HOOKS_DIR / "denial_watch.py").is_file())

    def test_a_missing_script_exits_0_silently_and_a_present_one_runs_as_before(self):
        root = temp_dir(self, "olivercode-failopen-", resolve=True)
        hooks = root / "dir with space" / "scripts" / "hooks"
        hooks.mkdir(parents=True)
        script = hooks / "gh_watch.py"
        script.write_text("import sys\nprint('got ' + sys.stdin.read())\nsys.exit(3)\n")
        cmd = claude_settings._command("gh_watch.py", hooks)
        run = lambda: subprocess.run(cmd, shell=True, input="hello", capture_output=True, text=True)
        ran = run()
        self.assertEqual((3, "got hello\n"), (ran.returncode, ran.stdout))
        script.unlink()
        gone = run()
        self.assertEqual((0, "", ""), (gone.returncode, gone.stdout, gone.stderr))

    def test_an_old_form_entry_is_recognised_and_replaced_not_duplicated(self):
        hooks = Path("/oc/scripts/hooks")
        old = {"type": "command", "command": 'python3 "/oc/scripts/hooks/gh_watch.py"'}
        merged = claude_settings.merge({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [old]}]}}, hooks)
        commands = [h["command"] for g in merged["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertEqual([claude_settings._command("gh_watch.py", hooks)], commands)
        self.assertIn("gh_watch.py", claude_settings.missing(Path("/nowhere.json"), hooks))
        self.assertEqual([], claude_settings.missing_for(merged, hooks) if hasattr(claude_settings, "missing_for") else [])
        self.assertEqual(claude_settings.without(merged).get("hooks"), None)

    def test_dead_names_a_new_form_entry_and_health_reports_it_without_the_instruction_link(self):
        from lib import cmd_health
        home = temp_dir(self, "olivercode-deadhome-", resolve=True)
        (home / ".claude").mkdir()
        (home / "scripts").mkdir()
        (home / "scripts" / "olivercode").write_text("")
        cmd = claude_settings._command("session_check.py", home / "scripts" / "hooks")
        (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": cmd}]}]}}))
        self.assertEqual([cmd], claude_settings.dead(home / ".claude" / "settings.json"))
        with mock.patch.object(Path, "home", staticmethod(lambda: home)), mock.patch.dict(os.environ, {"HOME": str(home)}):
            out = quiet(cmd_health.command_health)[1]
        self.assertFalse((home / ".claude" / "CLAUDE.md").exists())
        self.assertRegex(out, r"\[FAIL\].*do not exist.*session_check\.py")

    def test_dead_names_a_managed_entry_whose_script_does_not_exist(self):
        root = temp_dir(self, "olivercode-dead-", resolve=True)
        (root / "scripts" / "hooks").mkdir(parents=True)
        (root / "scripts" / "hooks" / "here.py").write_text("")
        (root / "scripts" / "olivercode").write_text("")
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
        hooks_dir = temp_dir(self, "olivercode-hooksdir-", resolve=True) / "scripts" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "still_here.py").write_text("")
        gone = {"type": "command", "command": f'python3 "{hooks_dir}/gone.py"'}
        other = temp_dir(self, "someone-elses-project-", resolve=True)  # exists and holds no scripts/olivercode
        lost = {"type": "command", "command": 'python3 "/no/such/checkout/scripts/hooks/gone.py"'}  # its checkout is gone from disk
        kept = [{"type": "command", "command": c} for c in (
            f'python3 "{hooks_dir}/still_here.py"',  # an unmanaged script of this checkout
            f'python3 "{other}/scripts/hooks/gone.py"',  # another project's folder
            f'python3 "{hooks_dir}/gone.py" --flag',  # not the form install writes
            "~/mine.sh")]
        settings = {"hooks": {"PostToolUse": [{"hooks": [gone]}, {"matcher": "Bash", "hooks": [gone, lost, *kept]}]}}
        merged = claude_settings.merge(settings, hooks_dir)
        commands = [h["command"] for groups in merged["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertNotIn(gone["command"], commands)
        self.assertNotIn(lost["command"], commands)  # under a checkout that no longer exists it can only fail, so it goes
        self.assertNotIn(kept[0]["command"], commands)  # the script exists but this version does not manage it, so it goes
        kept = kept[1:]
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
            self.assertIn("Confirm any figure", text, prompt)
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
        entry = {"type": "command", "command": f'python3 "{REPO_ROOT}/scripts/hooks/design_hook.py"'}
        self.assertEqual({}, claude_settings.without({"hooks": {"Stop": [{"hooks": [entry]}]}}))
