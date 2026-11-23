"""fleet-sync pushes a level-able repo, pulls a behind one and queues a dirty one without touching it (#626)."""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_fleetsync, cmd_owner  # noqa: E402


class TestFleetSync(unittest.TestCase):
    def test_sync_levels_clean_repos_and_queues_the_rest(self):
        root = temp_dir(self)
        origin = scratch_repo(root / "origin.git", bare=True, branch="main")
        seed = scratch_repo(root / "seed", branch="main")
        (seed / "a.txt").write_text("1\n")
        git(seed, "add", "a.txt")
        git(seed, "commit", "-q", "-m", "one")
        git(seed, "remote", "add", "origin", str(origin))
        git(seed, "push", "-q", "-u", "origin", "main")
        repos = []
        for name in ("ahead", "behind", "dirty"):
            git(root, "clone", "-q", str(origin), name)
            git(root / name, "config", "user.email", "t@example.test")
            git(root / name, "config", "user.name", "t")
            repos.append((name, root / name))
        (root / "ahead" / "b.txt").write_text("2\n")
        git(root / "ahead", "add", "b.txt")
        git(root / "ahead", "commit", "-q", "-m", "two")
        (seed / "c.txt").write_text("3\n")
        git(seed, "add", "c.txt")
        git(seed, "commit", "-q", "-m", "three")
        git(seed, "push", "-q")
        (root / "dirty" / "a.txt").write_text("edited\n")
        lines = []
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(root / "home")}), \
                mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_fleetsync.run(repos, check=lambda path: (0, ""), out=lines.append)
                cmd_fleetsync.run(repos, check=lambda path: (0, ""), out=lines.append)
            queue = cmd_owner.items()
        text = "\n".join(lines)
        self.assertIn("ahead: pushed 1 commit(s)", text)
        self.assertIn("two", git(origin, "log", "--format=%s").stdout)
        self.assertTrue((root / "behind" / "c.txt").is_file())
        self.assertIn("dirty: 1 uncommitted file(s)", text)
        self.assertEqual("edited\n", (root / "dirty" / "a.txt").read_text())
        self.assertEqual(1, len(queue))
        self.assertIn("dirty", queue[0]["step"])


if __name__ == "__main__":
    unittest.main()
