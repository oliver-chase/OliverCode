import atexit
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import audit_ledger
import ledger_report
from test_audit_ledger import commit, repo


class LedgerReport(unittest.TestCase):
    def setUp(self):
        # The machine's olivercode.local.json lists its personal repos, and GitHub answers for archived ones; neither may change a result.
        self.enterContext(unittest.mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": os.devnull, "OLIVERCODE_ARCHIVED": "off"}))

    def test_personal_repo_is_skipped(self):
        root = Path(tempfile.mkdtemp())
        atexit.register(shutil.rmtree, root, True)
        (root / "mine").symlink_to(repo({"a.txt": "one\n"}))
        (root / "other").symlink_to(repo({"a.txt": "one\n"}))
        with unittest.mock.patch.object(ledger_report, "personal_repos", return_value={"mine"}):
            self.assertEqual([p.name for p in ledger_report.repos(root)], ["other"])


    def test_states(self):
        root = Path(tempfile.mkdtemp())
        atexit.register(shutil.rmtree, root, True)
        fresh = repo({"a.txt": "one\n"})
        audit_ledger.mark(fresh, ["a.txt"])
        commit(fresh, {"docs/AUDITED.txt": (fresh / "docs/AUDITED.txt").read_text()})
        stale = repo({"a.txt": "one\n"})
        audit_ledger.mark(stale, ["a.txt"])
        commit(stale, {"a.txt": "two\n"})
        none = repo({"a.txt": "one\n"})
        for name, src in (("fresh", fresh), ("stale", stale), ("none", none)):
            (root / name).symlink_to(src)
        states = {r[0]: r[1] for r in map(ledger_report.row, ledger_report.repos(root))}
        self.assertEqual(states, {"fresh": "current", "stale": "stale", "none": "unaudited"})
        steps = ledger_report.next_steps(list(map(ledger_report.row, ledger_report.repos(root))), root)
        self.assertEqual(len(steps), 2)
        unaudited = next(s for s in steps if s.startswith("unaudited"))
        self.assertIn(f"audit_ledger.py {root / 'none'} --pending", unaudited)
        self.assertFalse(any(" fresh:" in s for s in steps))


if __name__ == "__main__":
    unittest.main()
