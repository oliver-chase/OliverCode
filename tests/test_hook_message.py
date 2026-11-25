"""Every hook refusal and advice is one line of at most 200 characters that names a doc section (#893)."""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
from lib import claude_settings, hook_message  # noqa: E402

LONG = "A policy refusal that names the path " + "deep/" * 60 + "file.txt and the pattern it matched."


class TestBounded(unittest.TestCase):
    def test_a_long_message_is_cut_to_the_limit_and_keeps_a_doc_pointer(self):
        out = hook_message.bounded(LONG)
        self.assertLessEqual(len(out), hook_message.LIMIT)
        self.assertTrue(out.endswith("See docs/RULES.md, Execution."))
        self.assertNotIn("\n", out)

    def test_a_pointer_the_message_already_has_survives_the_cut(self):
        out = hook_message.bounded(LONG + " See docs/GATES.md, Validation.")
        self.assertLessEqual(len(out), hook_message.LIMIT)
        self.assertTrue(out.endswith("See docs/GATES.md, Validation."))

    def test_a_short_message_with_a_pointer_is_unchanged_and_one_with_none_gets_the_default(self):
        short = "Stop retrying it. See docs/RULES.md, Prepared owner steps."
        self.assertEqual(short, hook_message.bounded(short))
        self.assertEqual("Nope. See docs/RULES.md, Execution.", hook_message.bounded("Nope."))

    def test_lines_are_joined(self):
        self.assertNotIn("\n", hook_message.bounded("one\ntwo\n\nthree"))


class TestEveryHookEmitsBoundedMessages(unittest.TestCase):
    def test_pretool_guard_bounds_a_deny_an_ask_and_the_queue_note(self):
        import pretool_guard
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "x"}, "cwd": str(REPO_ROOT)})
        for kind in ("deny", "ask"):
            out = io.StringIO()
            with mock.patch.object(pretool_guard, "verdicts", return_value=[(kind, LONG)]), \
                    mock.patch.object(pretool_guard, "updated_input", return_value=None), \
                    mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(out):
                pretool_guard.main()
            reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertLessEqual(len(reason), hook_message.LIMIT, kind)
            self.assertIn("docs/", reason)

    def test_the_stop_hook_reasons_fit_and_name_a_doc(self):
        import importlib
        stop = importlib.import_module("early-stop-guard")
        for reason in (stop.PROMISE_REASON, stop.HANDOFF_REASON):
            self.assertLessEqual(len(reason), hook_message.LIMIT)
            self.assertIn("docs/", reason)

    def test_every_registered_hook_that_refuses_or_advises_goes_through_the_bound(self):
        """A hook that prints a refusal or advice without `hook_message.bounded` fails here. The reports a hook prints as data are listed: the design check, the
        status digest and the session-start summary are findings or status, not refusals."""
        reports = {"design_hook.py", "status_hint.py", "session_check.py", "gh_watch.py", "wip_save.py", "owner_decision_capture.py"}
        for _, _, script in claude_settings.MANAGED:
            if script in reports:
                continue
            text = (REPO_ROOT / "scripts" / "hooks" / script).read_text()
            self.assertIn("hook_message.bounded", text, f"{script} prints a refusal or advice without the bound")


if __name__ == "__main__":
    unittest.main()
