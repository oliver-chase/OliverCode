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

HOOK = REPO_ROOT / "scripts" / "hooks" / "owner_decision_capture.py"


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

    def test_the_brief_holds_at_most_the_last_five_entries_and_800_characters(self):
        for i in range(60):
            owner_decisions.record(f"Story #40: [decision-{i:02d}] " + "x" * 300, "s1")
        section = owner_decisions.brief_section(40)
        self.assertLessEqual(len(section), owner_decisions.BRIEF_CHARS)
        self.assertIn("[decision-59]", section)
        self.assertNotIn("[decision-54]", section)

    def test_a_single_long_message_is_cut_to_the_brief_limit(self):
        owner_decisions.record("Story #40: " + "y" * 4000, "s1")
        self.assertLessEqual(len(owner_decisions.brief_section(40)), owner_decisions.BRIEF_CHARS)

    def test_the_file_is_trimmed_to_its_limit_and_keeps_the_newest_lines(self):
        with mock.patch.object(owner_decisions, "MAX_ROWS", 3):
            for i in range(5):
                owner_decisions.record(f"Story #40: note {i}", "s1")
        lines = (self.home / owner_decisions.FILE).read_text().splitlines()
        self.assertEqual([json.loads(line)["text"] for line in lines], ["Story #40: note 2", "Story #40: note 3", "Story #40: note 4"])

    def test_legacy_runner_prompts_are_removed_but_owner_data_is_preserved(self):
        path = self.home / owner_decisions.FILE
        rows = [
            {"story": 79, "at": "old", "session": "runner", "text": "You are a fresh reader. Check story #79."},
            {"story": 80, "at": "old", "session": "runner", "text": "Builder brief for story #80\\nContext follows"},
            {"story": 81, "at": "old", "session": "owner", "text": "Please treat this as a fresh reader exercise for #81"},
            {"story": 82, "at": "old", "session": "owner", "text": "I want to build #82"},
        ]
        path.write_text("".join(json.dumps(row) + "\\n" for row in rows), encoding="utf-8")
        self.assertEqual(owner_decisions.entries(79), [])
        self.assertEqual(owner_decisions.entries(80), [])
        self.assertEqual(len(owner_decisions.entries(81)), 1)
        self.assertEqual(len(owner_decisions.entries(82)), 1)
        remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["story"] for row in remaining], [81, 82])
        self.assertEqual(owner_decisions.cleanup_legacy(), 0)

    def test_legacy_cleanup_preserves_malformed_lines(self):
        path = self.home / owner_decisions.FILE
        path.write_text("not-json\\n" + json.dumps({"story": 83, "text": "You are a fresh reader"}) + "\\n", encoding="utf-8")
        self.assertEqual(owner_decisions.cleanup_legacy(), 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "not-json\\n")

    def test_the_hook_records_owner_prompts_but_skips_headless_prompts(self):
        def run(prompt, headless=False):
            env = os.environ.copy()
            if headless:
                env["OLIVERCODE_HEADLESS"] = "1"
            else:
                env.pop("OLIVERCODE_HEADLESS", None)
            subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": "s9", "prompt": prompt}),
                           text=True, capture_output=True, env=env, check=True)
        run("Please build #77 with a flat file")
        run("Another Claude session sent a message: finish #78")
        run("You are a fresh reader. Check story #79.", headless=True)
        run("Builder brief for story #80", headless=True)
        self.assertEqual(len(owner_decisions.entries(77)), 1)
        self.assertEqual(owner_decisions.entries(78), [])
        self.assertEqual(owner_decisions.entries(79), [])
        self.assertEqual(owner_decisions.entries(80), [])

    def test_a_decision_stated_after_the_lesson_hook_is_removed_is_recorded_and_briefed(self):
        subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": "s3", "prompt": "Story #46: the ledger keeps this decision"}),
                       text=True, capture_output=True, env=os.environ.copy(), check=True)
        self.assertEqual(len(owner_decisions.entries(46)), 1)
        self.assertIn("the ledger keeps this decision", owner_decisions.brief_section(46))

    def test_the_new_hook_is_registered_for_user_prompt_submit(self):
        from lib import claude_settings
        self.assertIn(("UserPromptSubmit", None, "owner_decision_capture.py"), claude_settings.MANAGED)


if __name__ == "__main__":
    unittest.main()
