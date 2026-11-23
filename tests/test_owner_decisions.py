"""#884: an owner message that names a story is saved by the lesson_capture hook and reaches that story's builder."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import owner_decisions  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "lesson_capture.py"


class TestOwnerDecisions(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_brief_holds_none_of_a_decision_before_it_is_recorded(self):
        self.assertEqual(owner_decisions.brief_section(40), "")

    def test_a_prompt_naming_a_story_is_appended_once_per_story(self):
        self.assertEqual(owner_decisions.record("Do #12 first, then #40, and #12 again", "s1"), 2)
        self.assertEqual([r["story"] for r in json.loads("[" + ",".join((self.home / owner_decisions.FILE).read_text().splitlines()) + "]")], [12, 40])

    def test_a_prompt_naming_no_story_writes_nothing(self):
        self.assertEqual(owner_decisions.record("hello there, issue#3 and a#b"), 0)
        self.assertFalse((self.home / owner_decisions.FILE).exists())

    def test_the_brief_of_story_40_holds_only_its_entries(self):
        owner_decisions.record("Story #12: use sqlite", "s1")
        owner_decisions.record("Story #40: keep the file as JSON lines", "s2")
        section = owner_decisions.brief_section(40)
        self.assertIn("keep the file as JSON lines", section)
        self.assertNotIn("sqlite", section)

    def test_the_hook_records_an_owner_prompt_and_skips_another_sessions_message(self):
        def run(prompt):
            subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": "s9", "prompt": prompt}),
                           text=True, capture_output=True, env=os.environ.copy(), check=True)
        run("Please build #77 with a flat file")
        run("Another Claude session sent a message: finish #78")
        self.assertEqual(len(owner_decisions.entries(77)), 1)
        self.assertEqual(owner_decisions.entries(78), [])


if __name__ == "__main__":
    unittest.main()
