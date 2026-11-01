"""Tests for commit_paths.py and precheck.py. Run: python3 -m unittest test_commit_tools (from this folder)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import commit_paths
import precheck


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def make_repo():
    repo = Path(tempfile.mkdtemp())
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t" + "@" + "example.com")  # built so the PII scan sees no literal
    git(repo, "config", "user.name", "T")
    (repo / "keep.txt").write_text("keep\n")
    (repo / "gone.txt").write_text("gone\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def files(repo, name, lines):
    path = repo / name
    path.write_text("\n".join(lines) + "\n")
    return path


class CommitPaths(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()
        self.msg = files(self.repo.parent, f"{self.repo.name}-msg.txt", ["a change"])

    def commit(self, paths, wait=1):
        listing = files(self.repo.parent, f"{self.repo.name}-paths.txt", paths)
        return commit_paths.commit(self.repo, self.msg, listing, wait)

    def test_a_peers_staged_file_stays_out_of_the_commit(self):
        (self.repo / "mine.txt").write_text("mine\n")
        (self.repo / "peer.txt").write_text("peer\n")
        git(self.repo, "add", "peer.txt")
        code, _ = self.commit(["mine.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=", "HEAD").split(), ["mine.txt"])
        self.assertIn("peer.txt", git(self.repo, "diff", "--cached", "--name-only"))

    def test_a_deleted_path_is_committed_as_a_deletion(self):
        (self.repo / "gone.txt").unlink()
        code, _ = self.commit(["gone.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(git(self.repo, "show", "--name-status", "--format=", "HEAD").split(), ["D", "gone.txt"])

    def test_a_locked_index_returns_2_after_the_wait(self):
        (self.repo / ".git" / "index.lock").write_text("")
        (self.repo / "mine.txt").write_text("mine\n")
        code, text = self.commit(["mine.txt"], wait=1)
        self.assertEqual(code, 2)
        self.assertIn("index.lock", text)

    def test_a_blocking_hook_prints_only_the_blocked_gate(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho '  [ok] fine gate'\necho '  [BLOCKED] bad gate'\necho '    file.md: broke a rule'\nexit 1\n")
        hook.chmod(0o755)
        (self.repo / "mine.txt").write_text("mine\n")
        code, text = self.commit(["mine.txt"])
        self.assertEqual(code, 1)
        self.assertIn("bad gate", text)
        self.assertIn("broke a rule", text)
        self.assertNotIn("fine gate", text)


class Precheck(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text(
            "#!/bin/bash\n"
            "echo '  [BLOCKED] gate on my file'\necho '    mine.md: broke a rule'\n"
            "echo '  [BLOCKED] gate on a peer file'\necho '    peer.md: broke a rule'\nexit 1\n")

    def test_every_blocked_gate_prints_and_the_peer_one_is_named(self):
        listing = files(self.repo.parent, f"{self.repo.name}-p.txt", ["mine.md"])
        code, output, peer = precheck.run(self.repo, listing)
        self.assertEqual(code, 1)
        self.assertIn("gate on my file", output)
        self.assertIn("gate on a peer file", output)
        self.assertEqual(peer, ["[BLOCKED] gate on a peer file"])

    def test_the_real_index_and_a_peers_staged_file_stay_untouched(self):
        (self.repo / "mine.md").write_text("mine\n")
        (self.repo / "peer.md").write_text("peer\n")
        git(self.repo, "add", "peer.md")
        before = git(self.repo, "diff", "--cached", "--name-only")
        listing = files(self.repo.parent, f"{self.repo.name}-q.txt", ["mine.md"])
        precheck.run(self.repo, listing)
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only"), before)


if __name__ == "__main__":
    unittest.main()
