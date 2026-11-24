"""Open stories: priority and owner-gate parsing, ranking and the REST read, with no network."""

import sys
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_groom  # noqa: E402
from lib import open_issues as page  # noqa: E402


def issue(n, title="T", body="", labels=()):
    return {"number": n, "title": title, "body": body, "labels": [{"name": l} for l in labels], "html_url": f"https://github.com/o/a/issues/{n}"}


class TestMemo(unittest.TestCase):
    def test_an_unchanged_story_is_read_once_and_a_changed_one_again(self):
        memo, reads = page.Memo(), []
        story = {"number": 7, "updated_at": "t1", "comments": 2}
        read = lambda: reads.append(1) or ["row"]
        self.assertEqual(["row"], memo.get("comments", story, read))
        self.assertEqual(["row"], memo.get("comments", dict(story), read))
        self.assertEqual(1, len(reads))
        memo.get("comments", {**story, "updated_at": "t2"}, read)
        self.assertEqual(2, len(reads))

    def test_a_failed_read_is_not_kept_and_forget_drops_one_kind(self):
        memo, story = page.Memo(), {"number": 7}
        self.assertIsNone(memo.get("blockers", story, lambda: None))
        self.assertEqual([], memo.get("blockers", story, lambda: []))
        memo.get("comments", story, lambda: ["c"])
        memo.forget("blockers")
        self.assertEqual([9], memo.get("blockers", story, lambda: [9]))
        self.assertEqual(["c"], memo.get("comments", story, lambda: ["new"]))


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

    def test_rank_prefers_the_story_that_unblocks_more_work(self):
        found = sorted([
            {**issue(3, body="Priority: P1"), "issue_dependencies_summary": {"total_blocking": 1}},
            {**issue(2, body="Priority: P1"), "issue_dependencies_summary": {"total_blocking": 2}},
            issue(1, body="Priority: P1"),
        ], key=page.rank)
        self.assertEqual([2, 3, 1], [i["number"] for i in found])

    def test_priority_mismatch_is_reported_without_rewriting_the_story(self):
        stories = {7: {"title": "The runner fails", "body": "Priority: P2. Size: S."}}
        self.assertEqual(["#7 states P2 but the scale suggests P1"], cmd_groom.priority_mismatches(stories))
        self.assertEqual("Priority: P2. Size: S.", stories[7]["body"])

    def test_priority_above_the_scale_is_not_a_mismatch(self):
        self.assertEqual([], cmd_groom.priority_mismatches({8: {"title": "Tidy", "body": "Priority: P0."}}))

    def test_fetch_skips_pull_requests_and_honours_a_hold(self):
        out = '[[{"number":1,"title":"a"},{"number":2,"pull_request":{}}]]'
        with mock.patch.object(page.gh_budget, "refusal", return_value=""), mock.patch.object(page.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out)):
            self.assertEqual([1], [i["number"] for i in page.fetch("o/a")])
        with mock.patch.object(page.gh_budget, "refusal", return_value="held"), mock.patch.object(page.subprocess, "run") as ran:
            self.assertIsNone(page.fetch("o/a"))
            ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
