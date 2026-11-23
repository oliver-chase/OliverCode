"""#1000: a status-only message is blocked with the digest lines as the reason, a mixed one goes through with context, and "ask:" passes unchanged."""

import json
import os
import subprocess
import sys
import unittest

from _support import REPO_ROOT, load_script, temp_dir

hint = load_script("scripts/hooks/status_hint.py")

DIGEST = """# Status digest
Written 2026-11-23 13:00 UTC.
Board: owner/repo: 3 open stories.

## Open, 2 in priority order
- #991 P1 The guide teaches efficient use
- #979 P1 Stories build one at a time

## Landed, the last five
- #985 A new thread starts from the digest
"""


class StatusOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)
        self.digest = self.tmp / "status-digest.md"
        self.digest.write_text(DIGEST, encoding="utf-8")

    def run_hook(self, prompt):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        env = dict(os.environ, OLIVERCODE_HOME=str(self.tmp))
        return subprocess.run([sys.executable, script], input=json.dumps({"prompt": prompt}), capture_output=True, text=True, env=env)

    def test_a_status_only_message_is_status_only(self):
        for prompt in ("what's building right now?", "when will it finish?", "what's the status?", "status?"):
            self.assertTrue(hint.is_status_only(prompt), prompt)
        self.assertFalse(hint.is_status_only("what's building and also fix the parser"))

    def test_a_mixed_message_goes_through_with_the_status_lines_as_context(self):
        prompt = "what's building right now? and fix the parser bug in cmd_land"
        self.assertFalse(hint.is_status_only(prompt))
        self.assertIn("Board: owner/repo: 3 open stories.", hint.context(prompt, self.digest))

    def test_an_ask_prefix_passes_a_status_question_through_unchanged(self):
        for prompt in ("ask: what is building?", "Ask: status?"):
            self.assertFalse(hint.is_status_only(prompt), prompt)
            self.assertEqual("", hint.context(prompt, self.digest), prompt)

    def test_the_hook_blocks_a_status_only_message_and_adds_context_for_a_mixed_one(self):
        status = self.run_hook("what is building?")
        self.assertEqual(0, status.returncode)
        blocked = json.loads(status.stdout)
        self.assertEqual("block", blocked["decision"])
        self.assertIn("Board: owner/repo: 3 open stories.", blocked["reason"])
        self.assertIn("additionalContext", self.run_hook("what is building? and fix the parser").stdout)
        self.assertEqual("", self.run_hook("ask: what is building?").stdout)
        self.assertEqual("", self.run_hook("fix the parser bug").stdout)


if __name__ == "__main__":
    unittest.main()
