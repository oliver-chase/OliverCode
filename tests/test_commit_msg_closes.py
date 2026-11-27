"""A commit message with a closing keyword moves no card. The card reads Complete only after the work lands (#1045)."""

import json
import subprocess
import unittest

from _support import REPO_ROOT, git_env, temp_dir
from test_commit_msg import CommitMsgCase, setUpModule  # noqa: F401 - unittest runs setUpModule per defining module, so this file borrows the template


class TestClosesCard(CommitMsgCase):
    def setUp(self):
        super().setUp()
        self.first_commit()
        self.oc_home = temp_dir(self, "olivercode-home-")
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

    def test_a_closing_keyword_queues_nothing_and_the_commit_passes(self):
        for n, word in enumerate(("closes", "Closed", "resolved:")):
            with self.subTest(word):
                done = self.commit_with(f"Ship it, {word} #{640 + n}")
                self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())

    def test_a_bare_reference_queues_nothing(self):
        done = self.commit_with("Ship it (#642)")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())

    def test_fix_stays_a_plain_reference(self):
        done = self.commit_with("Ship it, Fixes #642")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())

    def test_a_missing_config_does_not_block_a_closing_commit(self):
        self.config.unlink()
        done = self.commit_with("Ship it, closes #642")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual([], self.queued())


if __name__ == "__main__":
    unittest.main()
