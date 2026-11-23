"""Open stories: priority and owner-gate parsing, ranking and the REST read, with no network."""

import sys
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import open_issues as page  # noqa: E402


def issue(n, title="T", body="", labels=()):
    return {"number": n, "title": title, "body": body, "labels": [{"name": l} for l in labels], "html_url": f"https://github.com/o/a/issues/{n}"}


class TestOpenIssues(unittest.TestCase):
    def test_priority_comes_from_the_body_line_then_a_label(self):
        self.assertEqual("P1", page.priority(issue(1, body="Priority: P1. Size: S.")))
        self.assertEqual("P0", page.priority(issue(2, body="x", labels=["priority: P0"])))
        self.assertEqual("P2", page.priority(issue(3, labels=["P2"])))
        self.assertEqual("P1", page.priority(issue(4, body="Priority: P1", labels=["P3"])))
        self.assertEqual("", page.priority(issue(5, body="no line")))

    def test_owner_gate_reads_labels_only(self):
        self.assertTrue(page.owner_gated(issue(1, labels=["owner-gate"])))
        self.assertTrue(page.owner_gated(issue(5, labels=["owner-action"])))
        # #1075: prose never gates a story; a scenario that creates an owner step is still built
        self.assertFalse(page.owner_gated(issue(2, body="Then one open owner step names the board")))
        self.assertFalse(page.owner_gated(issue(3, body="Needs owner approval first")))
        self.assertFalse(page.owner_gated(issue(4, body="a normal story", labels=["bug"])))

    def test_rank_orders_by_priority_then_number(self):
        found = sorted([issue(3, body="Priority: P2"), issue(2, body="Priority: P0"), issue(1)], key=page.rank)
        self.assertEqual([2, 3, 1], [i["number"] for i in found])

    def test_fetch_skips_pull_requests_and_honours_a_hold(self):
        out = '[[{"number":1,"title":"a"},{"number":2,"pull_request":{}}]]'
        with mock.patch.object(page.gh_budget, "refusal", return_value=""), mock.patch.object(page.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out)):
            self.assertEqual([1], [i["number"] for i in page.fetch("o/a")])
        with mock.patch.object(page.gh_budget, "refusal", return_value="held"), mock.patch.object(page.subprocess, "run") as ran:
            self.assertIsNone(page.fetch("o/a"))
            ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
