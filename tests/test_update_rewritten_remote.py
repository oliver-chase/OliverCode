"""`olivercode update` saves the old main and realigns when origin rewrote its history (#1032)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import load_script

load_script("scripts/olivercode", "olivercode_rewritten")
from lib import update_state  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class RewrittenRemote(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)]))
        self.origin, self.clone = tmp / "origin", tmp / "clone"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.origin)], check=True)
        git(self.origin, "commit", "-q", "--allow-empty", "-m", "base")
        (self.origin / "f").write_text("old")
        git(self.origin, "add", "f")
        git(self.origin, "commit", "-q", "-m", "shared work")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)], check=True)
        (self.origin / "f").write_text("rewritten")
        git(self.origin, "commit", "-q", "-a", "--amend", "-m", "shared work")
        git(self.clone, "fetch", "-q")

    def test_a_replaced_commit_upstream_is_a_rewritten_remote(self):
        self.assertTrue(update_state.rewritten(self.clone))

    def test_a_local_commit_beside_a_new_release_is_not_rewritten(self):
        git(self.clone, "reset", "-q", "--hard", "@{u}")
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "my own work")
        git(self.origin, "commit", "-q", "--allow-empty", "-m", "release")
        git(self.clone, "fetch", "-q")
        self.assertFalse(update_state.rewritten(self.clone))

    def test_realign_saves_the_old_main_and_matches_the_upstream(self):
        old = git(self.clone, "rev-parse", "HEAD")
        backup, upstream = update_state.realign(self.clone)
        self.assertEqual((upstream, git(self.clone, "rev-parse", backup)), ("origin/main", old))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), git(self.clone, "rev-parse", "@{u}"))

    def test_a_checkout_only_behind_is_not_rewritten(self):
        git(self.clone, "reset", "-q", "--hard", "@{u}")
        self.assertFalse(update_state.rewritten(self.clone))


if __name__ == "__main__":
    unittest.main()
