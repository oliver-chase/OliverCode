"""The memory guard warns on a write to memory that names no skill, check or story, and never blocks."""

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from _support import load_script

guard = load_script("scripts/hooks/memory_guard.py", "memory_guard_under_test")
pretool = load_script("scripts/hooks/pretool_guard.py", "pretool_guard_for_memory")

MEM = "/repo/.claude-optimization/memory/USER.md"
AUTO = "/Users/x/.claude/projects/-Users-x-repo/memory/feedback.md"


def write(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


class TestMemoryGuard(unittest.TestCase):
    def test_a_rule_written_to_memory_is_refused_whatever_story_it_cites(self):
        self.assertIn("puts a rule into memory", guard.reason(write(MEM, "Always run the tests first.")))
        self.assertIn("puts a rule into memory", guard.reason(write(MEM, "Always run the tests first (#547).")))
        self.assertIn("puts a rule into memory", guard.reason(write(MEM, "Never skip it, see skills/audit and scripts/validate.sh.")))

    def test_auto_memory_is_never_written(self):
        self.assertIn("never written", guard.reason(write(AUTO, "The owner prefers short replies.")))

    def test_the_refusal_is_one_line_under_200_characters_and_names_its_doc(self):
        why = guard.reason(write(MEM, "Always run the tests first."))
        self.assertLessEqual(len(why), 200)
        self.assertIn("docs/", why)

    def test_an_owner_fact_in_local_memory_passes(self):
        self.assertEqual("", guard.reason(write(MEM, "The owner lives in Boston and reads on a phone.")))

    def test_a_write_elsewhere_is_ignored(self):
        self.assertEqual("", guard.reason(write("/repo/docs/notes.md", "Always do X.")))

    def test_a_memory_index_pointer_line_passes(self):
        pointer = write("/repo/.claude-optimization/memory/MEMORY.md", "- [User](USER.md) - owner preferences")
        self.assertEqual("", guard.reason(pointer))
        prose = write("/repo/.claude-optimization/memory/MEMORY.md", "Always do X.")
        self.assertNotEqual("", guard.reason(prose))

    def test_edit_and_multiedit_are_checked(self):
        edit = {"tool_input": {"file_path": MEM, "new_string": "Always do X."}}
        multi = {"tool_input": {"file_path": MEM, "edits": [{"new_string": "Do X (#12). Never Y."}]}}
        self.assertNotEqual("", guard.reason(edit))
        self.assertNotEqual("", guard.reason(multi))

    def test_a_shell_redirect_or_tee_into_memory_is_refused_and_quoted_text_is_not(self):
        for cmd in (f"echo 'Always X' >> {MEM}", f"echo hi | tee -a {AUTO}", "echo hi > ~/.claude/projects/p/memory/a.md"):
            self.assertNotEqual("", guard.reason({"tool_input": {"command": cmd}}), cmd)
        self.assertEqual("", guard.reason({"tool_input": {"command": f"cat {MEM}"}}))
        self.assertEqual("", guard.reason({"tool_input": {"command": f"echo 'Always X >> {MEM}' | cat"}}))
        self.assertEqual("", guard.reason({"tool_input": {"command": f"echo 'Always X' # > {MEM}"}}))

    def test_it_refuses_through_the_one_hook(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(write(MEM, "Always X")))), contextlib.redirect_stdout(out):
            pretool.main()
        decision = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertIn("rule into memory", decision["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
