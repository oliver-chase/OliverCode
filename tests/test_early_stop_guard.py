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
                             input=json.dumps({"transcript_path": str(path), "stop_hook_active": active}),
                             env={**os.environ, "TMPDIR": self.tmp.name})
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout or "{}").get("decision") == "block"

    def test_the_turn_that_asked_in_its_next_step_box_is_not_blocked(self):
        self.assertFalse(self.blocks(user("start phase 2"),
                                     tool(WRAP_UP, {"recap": "Done.", "ask": "Start phase 2?"}), result(),
                                     text(REAL_CLOSING)))

    def test_a_turn_that_asked_with_the_question_tool_is_not_blocked(self):
        self.assertFalse(self.blocks(user("go"), tool("AskUserQuestion", {"questions": []}), result(),
                                     text("I'll start once you pick an option.")))

    def test_a_step_that_waits_on_the_owners_answer_is_not_blocked(self):
        for closing in ("I'll start once you approve.", "I'll run it when you say go.", "I'll proceed after you confirm."):
            self.assertFalse(self.blocks(user("x"), text(closing)), closing)

    def test_a_plain_promise_still_blocks(self):
        self.assertTrue(self.blocks(user("x"), text("I'll implement the fix now.")))

    def test_a_next_step_box_with_no_question_does_not_excuse_a_promise(self):
        self.assertTrue(self.blocks(user("x"), tool(WRAP_UP, {"recap": "Done."}), result(),
                                    text("I'll implement the fix now.")))

    def test_a_question_from_an_earlier_turn_does_not_count(self):
        self.assertTrue(self.blocks(user("a"), tool(WRAP_UP, {"recap": "r", "ask": "Go?"}), result(), text("Asked."),
                                    user("yes"), text("I'll implement the fix now.")))

    def test_it_never_blocks_twice_in_a_row(self):
        self.assertFalse(self.blocks(user("x"), text("I'll implement the fix now."), active=True))


if __name__ == "__main__":
    unittest.main()
