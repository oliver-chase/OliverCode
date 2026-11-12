import tempfile
import unittest
from pathlib import Path

import done_check


def fake(outputs):
    """A runner that answers by the script name in the command."""
    def run(cmd, cwd):
        key = " ".join(map(str, cmd)) if isinstance(cmd, list) else cmd
        for needle, (rc, text) in outputs.items():
            if needle in key:
                return rc, text
        return 0, ""
    return run


def repo(readme="", accepted=""):
    root = Path(tempfile.mkdtemp())
    (root / "docs").mkdir()
    (root / "README.md").write_text(readme)
    if accepted:
        (root / "docs/AUDIT-ACCEPTED.md").write_text(accepted)
    return root


class DoneCheckTest(unittest.TestCase):
    def names(self, results):
        return {n for n, ok, _ in results if not ok}

    def test_all_clear_with_a_recorded_verdict_is_done(self):
        results = done_check.checks(repo("Sharing: portable\n"), run=fake({}))
        self.assertEqual(self.names(results), set())

    def test_missing_verdict_and_a_failing_validation_fail(self):
        results = done_check.checks(repo(), run=fake({"validate": (1, "boom\n")}))
        self.assertEqual(self.names(results), {"validation", "sharing verdict recorded"})

    def test_budget_overrun_voice_and_sweep_rows_fail(self):
        out = {"fleet_check": (0, "testSeconds: 70 is over the budget of 60\nvoice: 2 contrast framing\n"),
               "sweep.py": (0, "unused-def  a.py:3  dead\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))), {"budgets, voice and board", "sweep"})

    def test_an_accepted_row_is_not_counted(self):
        out = {"sweep.py": (0, "unused-def  a.py:3  dead\n")}
        root = repo("Sharing: portable\n", "Accepted: unused-def a.py:3 - runtime entry\n")
        self.assertEqual(self.names(done_check.checks(root, run=fake(out))), set())

    def test_personal_verdict_only_counts_secrets(self):
        out = {"portability.py": (1, "personal-email  someone-at-example  x\nhistory-secret  abc123  y\nsignals: none\nportability: 2 blocker(s)\n")}
        personal = done_check.checks(repo("Sharing: personal - uses my own notes\n"), run=fake(out))
        portable = done_check.checks(repo("Sharing: portable\n"), run=fake(out))
        self.assertIn("portability", self.names(personal))
        self.assertIn(("history-secret", "abc123"), done_check.rows(out["portability.py"][1]))
        self.assertIn("portability", self.names(portable))
        only_email = {"portability.py": (1, "personal-email  someone-at-example  x\nportability: 1 blocker(s)\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: personal - mine\n"), run=fake(only_email))), set())

    def test_epic_must_be_closed(self):
        out = {"issue view": (0, "OPEN\n"), "issue list": (0, "2\n")}
        results = done_check.checks(repo("Sharing: portable\n"), epics=[5], run=fake(out))
        self.assertEqual(self.names(results), {"epic #5 closed", "no open story under epic #5"})


if __name__ == "__main__":
    unittest.main()
