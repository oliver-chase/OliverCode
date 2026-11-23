"""Tests for scripts/hooks/early-stop-guard.py, the Claude Code Stop hook.

The guard sends a turn back to work when it ends by promising work it did not do. It must
not block a turn that ends waiting on the owner, including a finished turn whose question
sits in the turn's next-step tool call. Each case writes a real-shaped transcript and runs the hook as Claude Code does.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "early-stop-guard.py"
REAL_CLOSING = ("Another session has an uncommitted edit to `shared/repo-profiles.json` in OliverCode. "
                "It isn't mine, so I left it alone. Phase 2 rewrites that same file, so I'll check with "
                "whichever session made the edit before I start.")


def text(t):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}


def tool(name, payload):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": name, "input": payload}]}}


def result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def user(t):
    return {"type": "user", "message": {"role": "user", "content": t}}


WRAP_UP = "mcp__ccd_turn__wrap_up"


class EarlyStopGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def blocks(self, *entries, active=False):
        path = Path(self.tmp.name) / "t.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in entries))
        out = subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True,
                             input=json.dumps({"transcript_path": str(path), "stop_hook_active": active, "session_id": "sess-1"}),
                             env={**os.environ, "TMPDIR": self.tmp.name, "HOME": self.tmp.name, "OLIVERCODE_HOME": self.tmp.name,
                                  "OLIVERCODE_LOCAL_CONFIG": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull})
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout or "{}").get("decision") == "block"

    def test_a_finished_turn_that_says_open_the_dashboard_is_not_blocked(self):
        self.assertFalse(self.blocks(user("x"), text("Done. Open the dashboard in your browser to see it.")))

    def test_the_turn_that_asked_in_its_next_step_box_about_a_payment_is_not_blocked(self):
        self.assertFalse(self.blocks(user("start phase 2"),
                                     tool(WRAP_UP, {"recap": "Done.", "ask": "Pay the $40 invoice?"}), result(),
                                     text(REAL_CLOSING)))

    def test_any_question_put_to_the_owner_is_not_blocked(self):
        for ask in ("Deploy to production?", "Rotate the API key?", "Edit the owner's rules file CLAUDE.md?", "Approve the payment?"):
            self.assertFalse(self.blocks(user("x"), tool(WRAP_UP, {"recap": "Done.", "ask": ask}), result(), text("Done.")), ask)

    def test_a_blocked_ask_does_not_block_twice(self):
        self.assertFalse(self.blocks(user("x"), tool(WRAP_UP, {"recap": "r", "ask": "Start phase 2?"}), result(), text("Done."), active=True))

    def test_a_turn_that_asked_with_the_question_tool_is_not_blocked(self):
        self.assertFalse(self.blocks(user("go"), tool("AskUserQuestion", {"questions": [{"question": "Which token store should hold the key?", "options": []}]}), result(),
                                     text("I'll start once you pick an option.")))
        self.assertFalse(self.blocks(user("go"), tool("AskUserQuestion", {"questions": [{"question": "Which layout?", "options": [{"label": "A"}]}]}),
                                     result(), text("I'll start once you pick an option.")))

    def test_a_step_that_waits_on_the_owners_answer_is_not_blocked(self):
        for closing in ("I'll start once you approve.", "I'll run it when you say go.", "I'll proceed after you confirm."):
            self.assertFalse(self.blocks(user("x"), text(closing)), closing)

    def test_a_next_step_box_with_no_question_does_not_excuse_a_promise(self):
        self.assertTrue(self.blocks(user("x"), tool(WRAP_UP, {"recap": "Done."}), result(),
                                    text("I'll implement the fix now.")))

    def test_a_question_from_an_earlier_turn_does_not_count(self):
        self.assertTrue(self.blocks(user("a"), tool(WRAP_UP, {"recap": "r", "ask": "Go?"}), result(), text("Asked."),
                                    user("yes"), text("I'll implement the fix now.")))

    def test_a_promise_before_the_last_sentence_does_not_block(self):
        closing = "I fixed it. I'll mention the hook now runs on every commit. The tests pass."
        self.assertFalse(self.blocks(user("x"), text(closing)))

    def test_a_next_step_label_does_not_block(self):
        self.assertFalse(self.blocks(user("x"), text("The audit is filed. Next: file the follow-up story.")))

    def test_a_conditional_promise_does_not_block(self):
        for closing in ("Done. If you hit an error, I'll fix it then.", "All set; I will add more later if needed.",
                        "The fix is in. I'll run the tests when the build finishes."):
            self.assertFalse(self.blocks(user("x"), text(closing)), closing)

    def test_an_unconditional_promise_in_the_closing_sentence_blocks(self):
        # A plain promise, one after a full stop or a semicolon, and one that says "once more".
        for closing in ("I'll implement the fix now.", "The fix is written. I'll run the tests now.",
                        "I'll run the tests once more now.", "The fix is written; I'll run the tests now."):
            self.assertTrue(self.blocks(user("x"), text(closing)), closing)

    def test_a_handoff_with_no_attempt_blocks_and_a_report_with_no_step_passes(self):
        for closing in ("The service is down. You need to restart it from the dashboard.", "Please run the migration on your machine."):
            self.assertTrue(self.blocks(user("x"), text(closing)), closing)
        self.assertFalse(self.blocks(user("x"), text("The report is done and saved to docs/report.md.")))

    def test_a_copied_step_with_refusal_words_and_no_tool_call_blocks(self):
        for closing in ("I ran `olivercode install` and it returned a permission error, so you need to run it yourself.",
                        "The push failed with permission denied. Please add the deploy key to the repo settings."):
            self.assertTrue(self.blocks(user("x"), text(closing)), closing)

    def test_a_step_with_a_matching_refused_tool_call_passes(self):
        denied = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Permission denied"}]}}
        self.assertFalse(self.blocks(user("x"), tool("Bash", {"command": "olivercode install"}), denied,
                                     text("`olivercode install` was refused with permission denied, so you need to run it in your terminal.")))

    def test_a_step_whose_command_was_never_run_blocks_even_after_another_refusal(self):
        denied = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Permission denied"}]}}
        self.assertTrue(self.blocks(user("x"), tool("Bash", {"command": "gh pr merge 5"}), denied,
                                    text("You need to run `olivercode install` yourself, it needs permission.")))

    def test_a_step_that_ran_and_succeeded_is_not_a_refusal(self):
        self.assertTrue(self.blocks(user("x"), tool("Bash", {"command": "olivercode install"}), result(),
                                    text("Please run `olivercode install` yourself.")))

    def test_an_owner_list_written_to_the_morning_file_needs_a_refused_call(self):
        write = tool("Write", {"file_path": "/x/state/morning.md", "content": "Owner steps: you need to run `olivercode install`."})
        self.assertTrue(self.blocks(user("x"), write, result(), text("The morning file is written.")))
        denied = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Permission denied"}]}}
        self.assertFalse(self.blocks(user("x"), tool("Bash", {"command": "olivercode install"}), denied, write, result(),
                                     text("The morning file is written.")))

    def test_a_handoff_that_asks_the_owner_is_not_blocked(self):
        self.assertFalse(self.blocks(user("x"), text("You can run the migration if you want. Shall I wait?")))

    def test_a_question_mark_in_quoted_text_or_an_earlier_sentence_does_not_turn_the_check_off(self):
        """A `?` in code or a quote, or before the closing sentence, is not a question to the owner (#899)."""
        for closing in ('The test asserts `re.search("a?b", x)` and then I\'ll run the suite now.',
                        'The log said "why does it fail?" so I\'ll fix the cause now.',
                        'Is the cache stale? I checked it. I\'ll rebuild it now.'):
            self.assertTrue(self.blocks(user("x"), text(closing)), closing)
        self.assertFalse(self.blocks(user("x"), text("I found two fixes. Which one do you prefer?")))

    def test_it_never_blocks_twice_in_a_row(self):
        self.assertFalse(self.blocks(user("x"), text("I'll implement the fix now."), active=True))



if __name__ == "__main__":
    unittest.main()
