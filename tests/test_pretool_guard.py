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
        "memory_guard.reason": "",
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
    def test_each_guard_opinion_is_printed_as_its_one_decision(self):
        ask = policy.Decision("ask", "push", "A push needs the owner.")
        memory = {**BASH, "tool_input": {"command": "bash scripts/validate.sh"}}
        rows = (  # (guard opinions, payload, printed decision, printed reason or None when not asserted)
            ({"placement_guard__reason": "Repos live under /x."}, BASH, "deny", "Repos live under /x."),
            ({"memory_guard__reason": "Rules belong in a skill."}, memory, "deny", "Rules belong in a skill."),
            ({"policy_guard__decide": (ask, "repo"), "commit_guard__reason": "Commit without --no-verify."}, BASH, "deny", None),
            ({"policy_guard__decide": (ask, "repo")}, BASH, "ask", "A push needs the owner."),
        )
        for i, (opinions, payload, decision, reason) in enumerate(rows):
            with self.subTest(row=i), quiet_guards(**opinions), mock.patch.object(pretool.policy, "log_block"):
                out = run_main(payload)
                self.assertEqual(decision, out["permissionDecision"])
                if reason is not None:
                    self.assertEqual(reason, out["permissionDecisionReason"])

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

    def test_a_test_or_render_command_passes_unchanged(self):
        for command in ("pytest", "npm test", "ffmpeg -i a.mp4 b.mp4", "bash scripts/validate.sh"):
            with quiet_guards():
                self.assertIsNone(run_main({**BASH, "tool_input": {"command": command}}), command)


AGENT = {"tool_name": "Agent", "tool_input": {"prompt": "read", "subagent_type": "general-purpose"}, "cwd": "/tmp"}


class TestAgentDefaultModel(unittest.TestCase):
    def test_an_agent_call_with_no_model_is_allowed_on_sonnet(self):
        with quiet_guards():
            out = run_main(AGENT)
        self.assertEqual({"hookEventName": "PreToolUse", "permissionDecision": "allow",
                          "updatedInput": {**AGENT["tool_input"], "model": "sonnet"}}, out)

    def test_another_guards_deny_or_ask_wins_and_no_allow_is_printed(self):
        for kind in ("deny", "ask"):
            decision = policy.Decision(kind, "paths", "Held.")
            with self.subTest(kind=kind), quiet_guards(policy_guard__decide=(decision, "repo")), \
                    mock.patch.object(pretool.policy, "log_block"):
                out = run_main(AGENT)
                self.assertEqual((kind, "Held."), (out["permissionDecision"], out["permissionDecisionReason"]))
                self.assertNotIn("updatedInput", out)


class TestRegistration(unittest.TestCase):
    def test_one_entry_replaces_the_four_pre_tool_guards(self):
        # One process per Bash, Edit or Write call. The start-session guard matches only its own tool.
        pre = [m for m in claude_settings.MANAGED if m[0] == "PreToolUse" and m[1] and "Bash" in m[1]]
        self.assertEqual([("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit|Agent|Task|Monitor", "pretool_guard.py")], pre)

