"""A pasted traceback files one story and one owner-queue line, and a repeat paste files nothing (#716)."""

import json
import os
import subprocess
import sys
import unittest

from _support import REPO_ROOT, temp_dir

HOOK = REPO_ROOT / "scripts" / "hooks" / "error_paste.py"
TRACE = ("here is the error:\n```\nTraceback (most recent call last):\n  File \"dashboard.py\", line 3, in <module>\n    import numpy\n"
         "ModuleNotFoundError: No module named 'numpy'\n```\n")


class TestErrorPaste(unittest.TestCase):
    def repo_dir(self):
        d = temp_dir(self) / "repo"
        d.mkdir()
        subprocess.run(["git", "-C", str(d), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(d), "remote", "add", "origin", "https://github.com/someone/else.git"], check=True)
        return str(d)

    def run_hook(self, prompt, home, cwd=None):
        cwd = cwd or self.repo_dir()
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

    def test_prose_stories_and_secrets_file_nothing_and_a_user_repo_gets_no_epic(self):
        for prompt in ("the tab 'Shop' could not be read", "Story body: Traceback (most recent call last): is mentioned in prose",
                       "please add a button", TRACE.replace("\n```\n", "\ntoken=abcdef123456\n```\n")):
            self.assertEqual("", self.run_hook(prompt, temp_dir(self)), prompt)
        home = temp_dir(self)
        self.assertEqual("", self.run_hook(TRACE, home, cwd="/nonexistent"))
        indented = "see\n    Traceback (most recent call last):\n      File \"a.py\", line 1\n    KeyError: 'k'\n\nthanks"
        self.assertIn("candidate added", self.run_hook(indented, home))
        story = json.loads((home / "candidates.jsonl").read_text().splitlines()[0])
        self.assertNotIn("Epic:", story["body"])
        self.assertNotIn("thanks", story["body"])


if __name__ == "__main__":
    unittest.main()
