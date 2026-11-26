"""A pasted traceback files one story and one owner-queue line, and a repeat paste files nothing (#716)."""

import json
import os
import subprocess
import sys
import unittest

from _support import REPO_ROOT, temp_dir

HOOK = REPO_ROOT / "scripts" / "hooks" / "error_paste.py"
TRACE = ("here is the error:\nTraceback (most recent call last):\n  File \"dashboard.py\", line 3, in <module>\n    import numpy\n"
         "ModuleNotFoundError: No module named 'numpy'\n")


class TestErrorPaste(unittest.TestCase):
    def run_hook(self, prompt, home, cwd="/nonexistent"):
        env = {**os.environ, "OLIVERCODE_HOME": str(home), "HOME": str(home)}
        done = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                              input=json.dumps({"prompt": prompt, "session_id": "local_x", "cwd": cwd}))
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def test_a_traceback_files_one_story_and_one_queue_line_and_a_repeat_files_none(self):
        home = temp_dir(self)
        out = json.loads(self.run_hook(TRACE, home))
        self.assertIn("olivercode candidates", out["systemMessage"])
        stories = [json.loads(x) for x in (home / "candidates.jsonl").read_text().splitlines()]
        self.assertEqual(1, len(stories))
        self.assertIn("No module named 'numpy'", stories[0]["title"])
        self.assertIn("No module named 'numpy'", stories[0]["body"])
        self.assertIn("diagnosing-bugs", stories[0]["body"])
        self.assertEqual(1, len((home / "owner-queue.jsonl").read_text().splitlines()))
        self.assertEqual("", self.run_hook(TRACE, home))
        self.assertEqual(1, len((home / "candidates.jsonl").read_text().splitlines()))

    def test_could_not_be_read_files_a_story_and_plain_prompts_or_secrets_do_not(self):
        home = temp_dir(self)
        self.assertIn("candidate added", self.run_hook("the tab 'Shop' could not be read", home))
        self.assertEqual("", self.run_hook("please add a button", temp_dir(self)))
        self.assertEqual("", self.run_hook(TRACE + "token=abcdef123456\n", temp_dir(self)))


if __name__ == "__main__":
    unittest.main()
