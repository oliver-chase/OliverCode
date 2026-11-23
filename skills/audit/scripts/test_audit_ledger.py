import atexit
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import audit_ledger

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t", "GIT_AUTHOR_EMAIL": "t" + "@example.test",
       "GIT_COMMITTER_EMAIL": "t" + "@example.test", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def repo(files):
    root = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, root, True)
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
    def test_a_run_line_records_the_date_and_finding_count_and_survives_later_marks(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, ["a.py"], findings=3, today="2026-11-19")
        commit(root, {"a.py": "x = 2\n"})
        audit_ledger.mark(root, ["a.py", "b.py"])
        audit_ledger.mark(root, ["b.py"], findings=0, today="2026-11-20")
        self.assertEqual(audit_ledger.run_lines(root), ["# run 2026-11-19 findings 3 files 1", "# run 2026-11-20 findings 0 files 1"])
        self.assertEqual(audit_ledger.pending(root), [])
        listing = root / "read.txt"
        listing.write_text("a.py\n")
        self.assertEqual(audit_ledger.main(["audit_ledger.py", str(root), "--mark", str(listing), "--findings", "2"]), 0)
        self.assertEqual(len(audit_ledger.run_lines(root)), 3)

    def test_a_non_ascii_path_is_listed_and_marked_by_its_real_name(self):
        name = "AI\u2019s plan \u2014 v2.md"
        root = repo({name: "x\n"})
        self.assertEqual(audit_ledger.pending(root), [name])
        self.assertEqual(audit_ledger.mark(root, [name]), 1)
        self.assertEqual(audit_ledger.pending(root), [])
        # A ledger written before the fix holds git's quoted form, and it still counts as read.
        ledger = root / audit_ledger.LEDGER
        blob = ledger.read_text(encoding="utf-8").split(" ", 1)[0]
        ledger.write_text(f'{blob} "AI\\342\\200\\231s plan \\342\\200\\224 v2.md"\n', encoding="utf-8")
        self.assertEqual(audit_ledger.pending(root), [])

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

    def test_mark_reads_a_file_list_whose_paths_hold_spaces(self):
        import contextlib, io
        root = repo({"01 - Skills/a/SKILL.md": "x\n", "b.py": "y = 2\n"})
        listing = root / "read.txt"
        listing.write_text("01 - Skills/a/SKILL.md\n")
        with contextlib.redirect_stdout(io.StringIO()):
            audit_ledger.main(["audit_ledger.py", str(root), "--mark", str(listing)])
        self.assertEqual(audit_ledger.pending(root), ["b.py"])

    def test_a_ledger_path_deleted_from_head_is_named_as_gone_and_not_pending(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, list(audit_ledger.blobs(root)))
        subprocess.run(["git", "-C", str(root), "rm", "-q", "b.py"], check=True, capture_output=True, env=ENV)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "rm"], check=True, capture_output=True, env=ENV)
        self.assertEqual(audit_ledger.gone(root), ["b.py"])
        self.assertEqual(audit_ledger.pending(root), [])

    def test_a_deleted_file_leaves_the_ledger(self):
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, list(audit_ledger.blobs(root)))
        subprocess.run(["git", "-C", str(root), "rm", "-q", "b.py"], check=True, capture_output=True, env=ENV)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "rm"], check=True, capture_output=True, env=ENV)
        audit_ledger.mark(root, [])
        self.assertNotIn("b.py", audit_ledger.read_ledger(root))

    def test_batches_split_the_pending_files_and_cover_each_exactly_once(self):
        root = repo({"a/1.py": "x\n" * 2, "a/2.py": "x\n" * 2, "b/3.py": "x\n" * 2, "c/big.py": "x\n" * 9})
        audit_ledger.mark(root, ["a/1.py"])
        found = audit_ledger.batches(root, 4)
        self.assertEqual(found, [(["a/2.py", "b/3.py"], 4), (["c/big.py"], 9)])
        self.assertEqual(sorted(p for b, _ in found for p in b), audit_ledger.pending(root))
