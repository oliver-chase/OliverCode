import subprocess
import tempfile
import unittest
from pathlib import Path

import audit_ledger

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t", "GIT_AUTHOR_EMAIL": "t" + "@example.test",
       "GIT_COMMITTER_EMAIL": "t" + "@example.test", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}


def repo(files):
    root = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=ENV)
    run("init", "-q")
    commit(root, files)
    return root


def commit(root, files):
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
    for a in (("add", "."), ("commit", "-qm", "c")):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=ENV)


class LedgerTest(unittest.TestCase):
    def test_with_no_ledger_every_file_is_pending(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        self.assertEqual(audit_ledger.pending(root), ["a.py", "b.py"])

    def test_after_marking_all_nothing_is_pending(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, list(audit_ledger.blobs(root)))
        self.assertEqual(audit_ledger.pending(root), [])

    def test_a_changed_and_a_new_file_are_pending_and_an_untouched_file_is_not(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, list(audit_ledger.blobs(root)))
        commit(root, {"a.py": "x = 2\n", "c.py": "z = 3\n"})
        self.assertEqual(audit_ledger.pending(root), ["a.py", "c.py"])

    def test_marking_only_some_files_leaves_the_rest_pending(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        self.assertEqual(1, audit_ledger.mark(root, ["a.py", "gone.py"]))  # only a path at HEAD is recorded and counted
        self.assertEqual(audit_ledger.pending(root), ["b.py"])

    def test_seeding_from_an_earlier_commit_marks_files_as_they_were_then(self):
        root = repo({"a.py": "x = 1\n"})
        first = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        commit(root, {"a.py": "x = 9\n", "n.py": "n = 1\n"})
        audit_ledger.main(["audit_ledger.py", str(root), "--seed", first])
        self.assertEqual(audit_ledger.pending(root), ["a.py", "n.py"])

    def test_a_deleted_file_leaves_the_ledger(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, list(audit_ledger.blobs(root)))
        subprocess.run(["git", "-C", str(root), "rm", "-q", "b.py"], check=True, capture_output=True, env=ENV)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "rm"], check=True, capture_output=True, env=ENV)
        audit_ledger.mark(root, [])
        self.assertNotIn("b.py", audit_ledger.read_ledger(root))


if __name__ == "__main__":
    unittest.main()
