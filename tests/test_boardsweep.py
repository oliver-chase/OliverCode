"""`olivercode board sync`: closed issues complete their cards, open issues land on the board, and a GraphQL hold queues the writes (#798)."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_boardsweep as sweep  # noqa: E402

CONFIG = {"repoOwner": "o", "repoName": "r", "fields": {"status": {"options": {"Backlog": "1", "Complete": "2"}}}}


def card(number, status, repo="o/r"):
    return {"content": {"number": number, "repository": repo}, "status": status}


def issue(number, state):
    return {"number": number, "state": state, "title": "t"}


class TestPlan(unittest.TestCase):
    def test_a_closed_issue_with_an_unfinished_card_moves_to_complete(self):
        close, add = sweep.plan([card(1, "Backlog"), card(2, "Complete")], [issue(1, "CLOSED"), issue(2, "CLOSED")], CONFIG)
        self.assertEqual(([1], []), (close, add))

    def test_an_open_issue_with_no_card_is_added_and_one_with_a_card_is_left(self):
        close, add = sweep.plan([card(1, "Backlog")], [issue(1, "OPEN"), issue(2, "OPEN"), issue(3, "CLOSED")], CONFIG)
        self.assertEqual(([], [2]), (close, add))

    def test_a_card_of_another_repo_does_not_count(self):
        _, add = sweep.plan([card(2, "Backlog", repo="o/other")], [issue(2, "OPEN")], CONFIG)
        self.assertEqual([2], add)

    def test_the_request_names_each_status(self):
        self.assertEqual({"issues": [{"number": 1, "fields": {"status": "Complete"}}, {"number": 2, "fields": {"status": "Backlog"}}]},
                         sweep.request(CONFIG, [1], [2]))


class TestRun(unittest.TestCase):
    def go(self, items, issues, dry_run=False, held=""):
        applied, lines = [], []
        reader = lambda path: (CONFIG, items, issues)
        applier = lambda path, payload: applied.append(payload) or 0
        with mock.patch.object(sweep.gh_budget, "refusal", return_value=held):
            code = sweep.run(board_list=lambda: [("Alpha", Path("a.json"))], reader=reader, applier=applier, dry_run=dry_run, out=lines.append)
        return code, applied, lines

    def test_a_board_in_step_writes_nothing(self):
        code, applied, lines = self.go([card(1, "Complete")], [issue(1, "CLOSED")])
        self.assertEqual((0, [], ["Alpha: in step"]), (code, applied, lines))

    def test_a_dry_run_reports_and_writes_nothing(self):
        code, applied, lines = self.go([card(1, "Backlog")], [issue(1, "CLOSED")], dry_run=True)
        self.assertEqual((0, []), (code, applied))
        self.assertIn("dry run", lines[0])

    def test_a_sweep_hands_its_changes_to_the_batch_and_says_when_a_hold_queues_them(self):
        code, applied, lines = self.go([card(1, "Backlog")], [issue(1, "CLOSED"), issue(2, "OPEN")], held="GraphQL is on hold. Resets at noon.")
        self.assertEqual(0, code)
        self.assertEqual(2, len(applied[0]["issues"]))
        self.assertIn("queued until the GraphQL reset", lines[0])

    def test_an_unreadable_board_fails_without_writing(self):
        lines = []
        def reader(path):
            raise RuntimeError("the repo's issues could not be read through REST")
        code = sweep.run(board_list=lambda: [("Alpha", Path("a.json"))], reader=reader, applier=lambda *a: self.fail("wrote"), out=lines.append)
        self.assertEqual(1, code)
        self.assertIn("the sweep did not run", lines[0])

    def test_a_failed_write_exits_nonzero(self):
        with mock.patch.object(sweep.gh_budget, "refusal", return_value=""):
            code = sweep.run(board_list=lambda: [("A", Path("a"))], reader=lambda p: (CONFIG, [], [issue(1, "OPEN")]), applier=lambda p, r: 2, out=lambda t: None)
        self.assertEqual(1, code)


class TestCommand(unittest.TestCase):
    def test_a_bad_argument_prints_the_usage(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(1, sweep.command_board_sweep(["--nope"]))
        self.assertIn("Usage: olivercode board sync", buf.getvalue())

    def test_the_job_runs_every_thirty_minutes(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            plist = sweep.launchd.job(sweep.LABEL, ["board", "sync"], "board-sweep.out", StartInterval=1800)
        self.assertEqual(1800, plist["StartInterval"])
        self.assertEqual(["board", "sync"], plist["ProgramArguments"][-2:])
        self.assertEqual("com.olivercode.board-sweep", plist["Label"])


if __name__ == "__main__":
    unittest.main()
