"""A commit message with a closing keyword queues Status Complete for that card, or the commit is refused."""

import json
import os
import subprocess
import time
import unittest
from pathlib import Path

from _support import REPO_ROOT, git_env, temp_dir
from test_commit_msg import CommitMsgCase


class TestClosesCard(CommitMsgCase):
    def setUp(self):
        super().setUp()
        self.first_commit()
        self.oc_home = temp_dir(self, "olivercode-home-")
        # A held rate limit keeps the queue from calling GitHub, so the request stays in the queue file.
        (self.oc_home / "gh-limit.json").write_text(json.dumps({"until": time.time() + 3600}))
        cfg = json.loads((REPO_ROOT / "docs" / "backlog-config.json").read_text())
        cfg["repoOwner"] = ""
        self.config = self.repo / "docs" / "backlog-config.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps(cfg))

    def commit_with(self, message, launcher=None):
        (self.repo / "a.txt").write_text(message + "\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "a.txt"], env=git_env(), check=True)
        env = git_env(OLIVERCODE_HOME=str(self.oc_home), OLIVERCODE_LAUNCHER=launcher or str(REPO_ROOT / "scripts" / "olivercode"))
        return subprocess.run(["git", "-C", str(self.repo), "commit", "-m", message], env=env, capture_output=True, text=True)

    def queued(self):
        path = self.oc_home / "gh-project-queue.json"
        if not path.exists():
            return []
        return [(i["number"], i["fields"]) for job in json.loads(path.read_text()) for i in job["issues"]]

    def test_a_closing_keyword_queues_status_complete(self):
        for n, word in enumerate(("closes", "Closed", "resolved:")):
            with self.subTest(word):
                done = self.commit_with(f"Ship it, {word} #{640 + n}")
                self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([(640 + n, {"status": "Complete"}) for n in range(3)], self.queued())

    def test_a_bare_reference_queues_nothing(self):
        done = self.commit_with("Ship it (#642)")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())

    def test_fix_stays_a_plain_reference(self):
        done = self.commit_with("Ship it, Fixes #642")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())

    def test_a_missing_config_refuses_with_the_fix(self):
        self.config.unlink()
        done = self.commit_with("Ship it, closes #642")
        self.assertEqual(1, done.returncode)
        self.assertIn("olivercode backlog-setup --apply", done.stdout + done.stderr)

    def test_a_queue_that_cannot_take_the_request_refuses_with_the_fix(self):
        self.config.write_text("{}")
        done = self.commit_with("Ship it, closes #642")
        self.assertEqual(1, done.returncode)
        self.assertIn("olivercode backlog-setup --apply", done.stdout + done.stderr)
        self.assertEqual([], self.queued())


if __name__ == "__main__":
    unittest.main()
