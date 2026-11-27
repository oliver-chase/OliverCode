"""A repo GitHub archived or deleted is skipped by every fleet command and refused by a hook at a commit or push.

GitHub is never called: a fake `gh` first on PATH answers from the test, counts its calls and can fail like a
real one, and the helper tests inject a runner instead.
"""

import contextlib
import io
import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, quiet, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher_archived")
archived_guard = load_script("scripts/hooks/archived_guard.py", "archived_guard_under_test")
pretool = load_script("scripts/hooks/pretool_guard.py", "pretool_guard_archived_test")
from lib import cmd_fleet, maintain, placement, repo_state  # noqa: E402

AUDIT = str(REPO_ROOT / "skills" / "audit" / "scripts")
sys.path.insert(0, AUDIT)
import fleet_check  # noqa: E402

FAKE_GH = """#!/bin/sh
echo "$3" >> "$FAKE_GH_LOG"
case "$FAKE_GH_MODE" in
  offline) echo "error connecting to api.github.com" >&2; exit 1;;
  gone) echo "GraphQL: Could not resolve to a Repository with the name '$3'. (repository)" >&2; exit 1;;
esac
case " $FAKE_GH_ARCHIVED " in *" $3 "*) echo '{"isArchived": true}';; *) echo '{"isArchived": false}';; esac
"""


class FakeGh(unittest.TestCase):
    """A scratch fleet folder with one archived and one live checkout, and a fake gh that knows which is which."""

    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-archived-", resolve=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "gh.log"
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        env = mock.patch.dict(os.environ, {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "OLIVERCODE_ARCHIVED": "on",
            "OLIVERCODE_HOME": str(self.tmp / "home"), "FAKE_GH_LOG": str(self.log),
            "FAKE_GH_ARCHIVED": "acme/old-app", "FAKE_GH_MODE": ""})
        env.start()
        self.addCleanup(env.stop)
        repo_state.forget_said()
        self.old = self.checkout("old-app")
        self.live = self.checkout("live-app")

    def checkout(self, name, owner="acme"):
        repo = scratch_repo(self.fleet / name)
        git(repo, "remote", "add", "origin", f"https://github.com/{owner}/{name}.git")
        return repo

    def calls(self):
        return self.log.read_text().split() if self.log.exists() else []


class TestRepoState(unittest.TestCase):
    """The helper alone, with an injected runner."""

    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-state-", resolve=True)
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.tmp / "home"), "OLIVERCODE_ARCHIVED": "on"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = scratch_repo(self.tmp / "app")
        git(self.repo, "remote", "add", "origin", "git@github.com:acme/app.git")
        self.calls = []

    def runner(self, code=0, out='{"isArchived": true}', err=""):
        def run(args):
            self.calls.append(args)
            return code, out, err
        return run

    def test_answers_cache_and_the_cases_that_fail_open(self):
        clock = [1000.0]
        ask = lambda **kw: repo_state.archived(self.repo, runner=self.runner(**kw), clock=lambda: clock[0])  # noqa: E731
        self.assertEqual("archived", ask())
        self.assertEqual(["repo", "view", "acme/app", "--json", "isArchived"], self.calls[0])
        self.assertEqual("archived", ask(out='{"isArchived": false}'))
        self.assertEqual(1, len(self.calls), "a second answer inside a day comes from the cache")
        clock[0] += repo_state.TTL_SECONDS + 1
        self.assertIsNone(ask(out='{"isArchived": false}'))
        self.assertEqual(2, len(self.calls), "an expired answer asks GitHub again")
        self.assertIsNone(ask(), "an active answer is cached too")
        self.assertEqual(2, len(self.calls))
        clock[0] += repo_state.TTL_SECONDS + 1
        before = len(self.calls)
        self.assertIsNone(ask(code=1, err="GraphQL: Could not resolve to a Repository with the name 'acme/app'."))
        self.assertIsNone(ask(code=1, err="GraphQL: Could not resolve to a Repository with the name 'acme/app'."))
        self.assertEqual(before + 2, len(self.calls), "an unresolvable repo may be a wrong account, so it is never cached as deleted")
        clock[0] += repo_state.TTL_SECONDS + 1
        before = len(self.calls)
        for failure in ({"code": 1, "err": "error connecting to api.github.com"}, {"code": 1, "err": "HTTP 403: API rate limit exceeded"},
                        {"code": 1, "err": "HTTP 404: Not Found"}, {"code": 1, "err": "gh: repository not found"},
                        {"out": "not json"}, {"out": '{"other": 1}'}):
            self.assertIsNone(ask(**failure), failure)
        self.assertEqual(before + 6, len(self.calls), "a failed lookup is never cached")
        boom = mock.Mock(side_effect=OSError("no gh"))
        self.assertIsNone(repo_state.archived(self.repo, runner=boom, clock=lambda: clock[0]))
        no_origin = scratch_repo(self.tmp / "local")
        self.assertIsNone(repo_state.archived(no_origin, runner=self.runner()))
        git(no_origin, "remote", "add", "origin", "https://gitlab.com/acme/x.git")
        self.assertIsNone(repo_state.archived(no_origin, runner=self.runner()))
        self.assertIsNone(repo_state.archived(self.tmp / "missing", runner=self.runner()))
        with mock.patch.dict(os.environ, {"OLIVERCODE_ARCHIVED": "off"}):
            self.assertIsNone(repo_state.archived(self.repo, runner=self.runner(), clock=lambda: 9e9))


class TestEveryCommandSkips(FakeGh):
    def test_discover_does_not_list_it(self):
        oc = self.tmp / "oc"
        oc.mkdir()
        code, out = quiet(launcher.command_discover, oc, [self.fleet])
        self.assertEqual(0, code)
        self.assertIn("skip old-app: archived on GitHub", out)
        self.assertIn("live-app", out)
        self.assertNotRegex(out, r"old-app\s+rules=")

    def test_sync_hooks_leaves_it_untouched(self):
        shutil_templates = REPO_ROOT / "core" / "templates" / "project"
        with mock.patch.object(cmd_fleet, "_private_repos", return_value={"old-app": self.old, "live-app": self.live}), \
                mock.patch.object(cmd_fleet.repo_gates, "hook_templates", return_value=shutil_templates):
            code, out = quiet(launcher.command_sync_hooks, REPO_ROOT)
        self.assertEqual(0, code, out)
        self.assertIn("skip old-app: archived on GitHub", out)
        self.assertFalse((self.old / ".githooks").exists())
        self.assertTrue((self.live / ".githooks" / "pre-commit").is_file())

    def test_fleet_check_skips_it(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, fleet_check.main([str(self.old)]))
        self.assertEqual("skip old-app: archived on GitHub\n", out.getvalue())

    def test_backlog_setup_and_the_maintain_walk_skip_it(self):
        with mock.patch.object(cmd_fleet._backlog_setup, "run_setup") as setup:
            code, out = quiet(launcher.command_backlog_setup, [str(self.old), "--apply"])
        self.assertEqual(0, code)
        setup.assert_not_called()
        self.assertIn("skip old-app: archived on GitHub", out)
        cfg = placement.Config(root=self.fleet, worktrees=self.fleet / "_worktrees", archive=self.fleet / "_archive", watch=[], allow=[])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(["live-app"], [p.name for p in maintain._repos(cfg)])


class TestTheGuard(FakeGh):
    def deny(self, command, cwd=None):
        return archived_guard.reason(command, Path(cwd or self.tmp))

    def test_commit_and_push_are_denied_in_an_archived_or_deleted_checkout(self):
        for command in (f"git -C {self.old} commit -m x", f"git -C {self.old} push origin main",
                        f"cd {self.old} && git add -A && git commit -m x", f"cd {self.old} && git push",
                        f"bash -c 'cd {self.old} && git push'"):
            why = self.deny(command)
            self.assertIn("old-app is archived on GitHub", why, command)
            self.assertIn("Do not commit, push or change anything", why)
        self.assertIn("is archived", self.deny("git commit -m x", self.old))
        with mock.patch.dict(os.environ, {"FAKE_GH_MODE": "gone"}):
            self.assertEqual("", self.deny(f"git -C {self.live} push"), "an unresolvable repo is not proof of deletion")

    def test_a_normal_repo_and_other_git_commands_are_allowed(self):
        self.assertEqual("", self.deny(f"git -C {self.live} commit -m x"))
        self.assertEqual("", self.deny(f"cd {self.live} && git push"))
        self.assertEqual("", self.deny(f"git -C {self.old} status"))
        self.assertEqual("", self.deny(f"git -C {self.old} log --oneline"))
        self.assertEqual("", self.deny("ls"))

    def test_it_fails_open_on_a_lookup_failure_and_on_its_own_error(self):
        for mode in ("offline", "bogus"):
            with mock.patch.dict(os.environ, {"FAKE_GH_MODE": mode, "FAKE_GH_ARCHIVED": ""}):
                self.assertEqual("", self.deny(f"git -C {self.checkout('fresh-' + mode)} push"))
        self.assertEqual("", self.deny("git commit -m 'unterminated"))
        with mock.patch.object(archived_guard.repo_state, "archived", side_effect=RuntimeError("boom")):
            payload = {"tool_input": {"command": f"git -C {self.old} push"}, "cwd": str(self.tmp)}
            self.assertEqual([], pretool.verdicts(payload))

    def test_the_hook_denies_an_archived_repo_and_stays_silent_for_a_live_one(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": f"git -C {self.old} push"}, "cwd": str(self.tmp)}
        found = pretool.verdicts(payload)
        self.assertEqual("deny", found[0][0])
        self.assertIn("old-app is archived", found[0][1])
        import subprocess
        ran = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "hooks" / "pretool_guard.py")], input=json.dumps(payload),
                             capture_output=True, text=True, env=os.environ.copy())
        out = json.loads(ran.stdout)["hookSpecificOutput"]
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("archived on GitHub", out["permissionDecisionReason"])
        payload["tool_input"]["command"] = f"git -C {self.live} push"
        ran = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "hooks" / "pretool_guard.py")], input=json.dumps(payload),
                             capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual("", ran.stdout)


if __name__ == "__main__":
    unittest.main()
