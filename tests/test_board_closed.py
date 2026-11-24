"""A board update never reopens a closed issue, and the sweep lists one that a Status change reopened (#1121)."""

import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
import batch_project  # noqa: E402
import check_board_hygiene  # noqa: E402

CFG = {"repoOwner": "o", "repoName": "r", "projectId": "P",
       "fields": {"status": {"id": "S", "options": {"Backlog": "b", "Ready": "r", "Complete": "c"}},
                  "priority": {"id": "PR", "options": {"P1": "p1"}}}}


class FakeGh:
    def __init__(self, state):
        self.state, self.calls = state, []

    def __call__(self, args):
        self.calls.append(args)
        query = next((a for a in args if a.startswith("query=")), "")
        if "projectItems" in query:
            body = {"data": {"repository": {"i0": {"state": self.state, "projectItems": {"nodes": [{"id": "ITEM", "project": {"id": "P"}}]}}}}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {}}), stderr="")

    def mutations(self):
        return [a for call in self.calls for a in call if a.startswith("query=mutation")]

    def reopened(self):
        return [call for call in self.calls if "PATCH" in call]


class TestClosedGuard(unittest.TestCase):
    def setUp(self):
        for name in ("refusal", "reserve_write"):
            patcher = mock.patch.object(batch_project.gh_budget, name, return_value="")
            patcher.start()
            self.addCleanup(patcher.stop)

    def apply(self, issue, state):
        gh = FakeGh(state)
        return batch_project.drain(CFG, [issue], gh), gh

    def test_a_queued_status_change_leaves_a_closed_issue_closed_and_complete(self):
        for status in ("Backlog", "Ready"):
            (count, updates, skipped), gh = self.apply({"number": 7, "fields": {"status": status}}, "CLOSED")
            self.assertEqual((count, updates, skipped), (0, 0, [(7, f"status={status}")]))
            self.assertEqual((gh.mutations(), gh.reopened()), ([], []))

    def test_other_fields_of_a_closed_issue_still_apply(self):
        (_, updates, skipped), gh = self.apply({"number": 7, "fields": {"status": "Ready", "priority": "P1"}}, "CLOSED")
        self.assertEqual((updates, skipped), (1, [(7, "status=Ready")]))
        self.assertNotIn('"S"', gh.mutations()[0])

    def test_complete_on_a_closed_issue_and_any_change_on_an_open_one_apply(self):
        for issue, state in (({"number": 7, "fields": {"status": "Complete"}}, "CLOSED"), ({"number": 7, "fields": {"status": "Ready"}}, "OPEN")):
            (_, updates, skipped), gh = self.apply(issue, state)
            self.assertEqual((updates, skipped, gh.reopened()), (1, [], []))

    def test_the_reopen_flag_applies_the_change_and_reopens_the_issue(self):
        (_, updates, skipped), gh = self.apply({"number": 7, "fields": {"status": "Ready"}, "reopen": True}, "CLOSED")
        self.assertEqual((updates, skipped), (1, []))
        self.assertEqual(gh.reopened(), [["api", "-X", "PATCH", "repos/o/r/issues/7", "-f", "state=open"]])

    def test_merging_queued_work_keeps_the_reopen_flag(self):
        merged = batch_project.merge_issues([{"number": 7, "fields": {"status": "Ready"}, "reopen": True}, {"number": 7, "fields": {"priority": "P1"}}])
        self.assertEqual(merged, [{"number": 7, "fields": {"status": "Ready", "priority": "P1"}, "reopen": True}])

    def test_main_prints_the_skipped_change_and_takes_reopen_by_number(self):
        gh, queue = FakeGh("CLOSED"), []
        def with_queue(fn):
            result, queue[:] = fn(list(queue))
            return result
        with mock.patch.object(batch_project, "load", side_effect=[CFG, {"issues": [{"number": 7, "fields": {"status": "Backlog"}}]}]), \
                mock.patch.object(batch_project, "with_queue", with_queue), mock.patch.object(batch_project.board_mirror, "invalidate"):
            out = io.StringIO()
            batch_project.main(["--config", "c", "--input", "i"], runner=gh, out=out, err=io.StringIO())
        self.assertIn("skipped status=Backlog on closed #7", out.getvalue())
        self.assertEqual(gh.reopened(), [])
        with mock.patch.object(batch_project, "load", side_effect=[CFG, {"issues": [{"number": 7, "fields": {"status": "Backlog"}}]}]), \
                mock.patch.object(batch_project, "with_queue", with_queue), mock.patch.object(batch_project.board_mirror, "invalidate"):
            batch_project.main(["--config", "c", "--input", "i", "--reopen", "7"], runner=gh, out=io.StringIO(), err=io.StringIO())
        self.assertEqual(len(gh.reopened()), 1)


def event(kind, number, at, who="owner", state="open"):
    return {"event": kind, "created_at": at, "actor": {"login": who}, "issue": {"number": number, "title": f"Story {number}", "state": state}}


class TestReopenSweep(unittest.TestCase):
    def sweep(self, events):
        return check_board_hygiene.check_board_reopens({"repoOwner": "o", "repoName": "r"}, read=lambda args: json.dumps(events))

    def test_an_open_issue_reopened_by_a_status_change_is_listed_with_the_date(self):
        found = self.sweep([event("project_v2_item_status_changed", 41, "2026-11-24T16:14:00Z"), event("reopened", 41, "2026-11-24T16:13:59Z")])
        self.assertEqual(found, ['#41 "Story 41": reopened by a board Status change on 2026-11-24'])

    def test_a_reopen_by_hand_a_closed_issue_or_another_actor_is_not_listed(self):
        self.assertEqual(self.sweep([event("reopened", 41, "2026-11-24T16:13:59Z")]), [])
        self.assertEqual(self.sweep([event("project_v2_item_status_changed", 41, "2026-11-24T16:14:00Z", state="closed"),
                                     event("reopened", 41, "2026-11-24T16:13:59Z", state="closed")]), [])
        self.assertEqual(self.sweep([event("project_v2_item_status_changed", 41, "2026-11-24T16:14:00Z", who="bot"),
                                     event("reopened", 41, "2026-11-24T16:13:59Z")]), [])

    def test_an_unread_event_list_is_said_plainly(self):
        found = check_board_hygiene.check_board_reopens({"repoOwner": "o", "repoName": "r"}, read=lambda args: None)
        self.assertEqual(found, ["the repo's issue events were not read, so reopens were not checked"])


if __name__ == "__main__":
    unittest.main()
