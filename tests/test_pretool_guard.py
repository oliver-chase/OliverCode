"""The one PreToolUse hook that runs the commit, placement, policy and GitHub guards in a single process."""

import contextlib
import io
import json
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, load_script

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
import claude_settings  # noqa: E402
from lib import policy  # noqa: E402

pretool = load_script("scripts/hooks/pretool_guard.py", "pretool_guard_under_test")
SCRIPT = REPO_ROOT / "scripts" / "hooks" / "pretool_guard.py"


def run_main(payload):
    """The JSON the hook prints for this payload, or None when it prints nothing."""
    out = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(out):
        pretool.main()
    return json.loads(out.getvalue())["hookSpecificOutput"] if out.getvalue() else None


def quiet_guards(**replace):
    """Every guard says nothing unless a test gives it an opinion."""
    patches = {
        "commit_guard.reason": "",
        "placement_guard.reason": "",
        "gh_guard.refusal": "",
        "policy_guard.decide": (None, ""),
    }
    patches.update({k.replace("__", "."): v for k, v in replace.items()})
    stack = contextlib.ExitStack()
    for target, value in patches.items():
        module, name = target.split(".")
        stack.enter_context(mock.patch.object(getattr(pretool, module), name,
                                              side_effect=value if isinstance(value, Exception) else None,
                                              return_value=None if isinstance(value, Exception) else value))
    return stack


BASH = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": "/tmp"}


class TestDispatch(unittest.TestCase):
    def test_a_deny_from_one_guard_is_printed_with_its_reason(self):
        with quiet_guards(placement_guard__reason="Repos live under /x."):
            out = run_main(BASH)
        self.assertEqual(("deny", "Repos live under /x."), (out["permissionDecision"], out["permissionDecisionReason"]))

    def test_a_memory_rule_is_refused_with_its_reason(self):
        with quiet_guards(), mock.patch.object(pretool.memory_guard, "reason", return_value="Rules belong in a skill."):
            out = run_main({**BASH, "tool_input": {"command": "bash scripts/validate.sh"}})
        self.assertEqual(("deny", "Rules belong in a skill."), (out["permissionDecision"], out["permissionDecisionReason"]))

    def test_a_deny_wins_over_an_ask(self):
        ask = policy.Decision("ask", "push", "A push needs the owner.")
        with quiet_guards(policy_guard__decide=(ask, "repo"), commit_guard__reason="Commit without --no-verify."), \
                mock.patch.object(pretool.policy, "log_block"):
            out = run_main(BASH)
        self.assertEqual("deny", out["permissionDecision"])

    def test_an_ask_alone_is_printed_as_an_ask(self):
        ask = policy.Decision("ask", "push", "A push needs the owner.")
        with quiet_guards(policy_guard__decide=(ask, "repo")), mock.patch.object(pretool.policy, "log_block"):
            out = run_main(BASH)
        self.assertEqual(("ask", "A push needs the owner."), (out["permissionDecision"], out["permissionDecisionReason"]))

    def test_a_broken_guard_does_not_hide_the_others_or_block(self):
        with quiet_guards(commit_guard__reason=RuntimeError("bug"), placement_guard__reason="Repos live under /x."):
            self.assertEqual("deny", run_main(BASH)["permissionDecision"])
        with quiet_guards(commit_guard__reason=RuntimeError("bug"), gh_guard__refusal=RuntimeError("bug"),
                          policy_guard__decide=RuntimeError("bug"), placement_guard__reason=RuntimeError("bug")):
            self.assertIsNone(run_main(BASH))

    def test_a_github_write_is_not_counted_when_another_guard_already_refused(self):
        with quiet_guards(placement_guard__reason="Repos live under /x.") as _, \
                mock.patch.object(pretool.gh_guard, "refusal") as refusal:
            run_main(BASH)
        refusal.assert_not_called()

    def test_an_edit_skips_the_command_guards_and_still_reaches_the_policy(self):
        deny = policy.Decision("deny", "paths", "That path is denied.")
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x.txt"}, "cwd": "/tmp"}
        with quiet_guards(policy_guard__decide=(deny, "repo"), commit_guard__reason="never"), \
                mock.patch.object(pretool.policy, "log_block"):
            out = run_main(payload)
        self.assertEqual("That path is denied.", out["permissionDecisionReason"])

    def test_a_plain_command_prints_nothing_and_garbage_input_exits_zero(self):
        for stdin in ('{"tool_input": {"command": "ls"}, "cwd": "/tmp"}', "not json", "[]", ""):
            ran = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True)
            self.assertEqual((0, ""), (ran.returncode, ran.stdout), stdin)


class TestRegistration(unittest.TestCase):
    def test_one_entry_replaces_the_four_pre_tool_guards(self):
        # One process per Bash, Edit or Write call. The start-session guard matches only its own tool.
        pre = [m for m in claude_settings.MANAGED if m[0] == "PreToolUse" and m[1] and "Bash" in m[1]]
        self.assertEqual([("PreToolUse", "Bash|Edit|Write|MultiEdit|Agent|Task", "pretool_guard.py")], pre)

