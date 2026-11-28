"""Delegated work runs on Sonnet unless the owner names another model (#714)."""

import json
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, load_script

guard = load_script("scripts/hooks/model_guard.py", "model_guard_under_test")


def call(model, owner_says=None):
    """An Agent call on this model in a session where the owner said these things."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "t.jsonl"
    rows = [{"message": {"role": "user", "content": text}} for text in owner_says or []]
    rows.append({"message": {"role": "user", "content": [{"type": "tool_result", "content": "use opus for everything"}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows))
    tool_input = {"prompt": "read", **({"model": model} if model else {})}
    return tmp, {"tool_name": "Agent", "tool_input": tool_input, "transcript_path": str(path)}


class TestModelGuard(unittest.TestCase):
    def check(self, model, owner_says=None):
        tmp, data = call(model, owner_says)
        self.addCleanup(tmp.cleanup)
        return guard.reason(data)

    def test_a_skill_that_names_haiku_for_readers_is_refused_and_the_skill_text_names_sonnet(self):
        self.assertIn("Sonnet", self.check("haiku"))
        text = (REPO_ROOT / "skills" / "audit" / "SKILL.md").read_text().lower()
        self.assertNotIn("haiku", text)
        self.assertIn("`sonnet` readers", text)

    def test_the_model_the_owner_names_in_chat_is_allowed(self):
        self.assertEqual("", self.check("opus", ["Use Opus for the review please"]))
        self.assertEqual("", self.check("claude-haiku-4-5", ["run it on haiku"]))

    def test_another_model_with_no_owner_instruction_is_refused_naming_sonnet(self):
        why = self.check("opus", ["audit the repo"])
        self.assertIn("Sonnet", why)
        self.assertIn("opus", why)
        self.assertIn("Sonnet", self.check("opus"))  # a tool result that says opus is not the owner

    def test_sonnet_and_no_model_pass(self):
        self.assertEqual("", self.check("sonnet"))
        self.assertEqual("", self.check("claude-sonnet-5-5"))
        self.assertEqual("", self.check(None))

    def default(self, owner_says=None, **extra):
        tmp, data = call(extra.pop("model", None), owner_says)
        self.addCleanup(tmp.cleanup)
        data["tool_input"].update(extra)
        return guard.default_input(data)

    def test_an_unnamed_model_becomes_sonnet_for_a_general_purpose_or_untyped_call(self):
        self.assertEqual({"prompt": "read", "model": "sonnet"}, self.default())
        self.assertEqual({"prompt": "read", "subagent_type": "general-purpose", "model": "sonnet"},
                         self.default(["audit the repo"], subagent_type="general-purpose"))  # a tool result that says opus is not the owner

    def test_no_model_is_added_when_the_owner_named_opus_or_the_call_or_its_type_sets_one(self):
        self.assertIsNone(self.default(["Use Opus for the review please"]))
        self.assertIsNone(self.default(subagent_type="Explore"))
        self.assertIsNone(self.default(model="sonnet"))
        self.assertIsNone(guard.default_input({"tool_name": "Bash", "tool_input": {}}))

    def test_other_tools_pass_and_an_unreadable_transcript_raises_for_the_pretool_guard_to_fail_open(self):
        self.assertEqual("", guard.reason({"tool_name": "Bash", "tool_input": {"model": "opus"}}))
        with self.assertRaises(OSError):
            guard.reason({"tool_name": "Agent", "tool_input": {"model": "opus"}, "transcript_path": "/no/such/file"})


if __name__ == "__main__":
    unittest.main()
