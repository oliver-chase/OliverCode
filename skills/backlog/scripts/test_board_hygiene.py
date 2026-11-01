"""Test the sweep checks (status drift, required fields, duplicate cards, stale, Area policy), the REST reads and the config guards.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import datetime
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import check_board_hygiene as bh

CONFIG = {"repoOwner": "o", "repoName": "r", "fields": {"area": {}}}


def item(number, status, area="gtm"):
    content = {"number": number, "repository": "o/r", "title": "t"}
    return {"content": content, "status": status, "area": area, "priority": "P1", "size": "S", "work Type": "Story"}


class Drift(unittest.TestCase):
    def setUp(self):
        self.real_run_gh = bh.run_gh
        bh.run_gh = lambda args: json.dumps([
            {"number": 1, "state": "CLOSED", "title": "t"},
            {"number": 2, "state": "OPEN", "title": "t"},
            {"number": 3, "state": "OPEN", "title": "t"},
        ])

    def tearDown(self):
        bh.run_gh = self.real_run_gh

    def test_closed_issue_on_open_status_and_open_issue_off_board_are_flagged(self):
        problems = bh.check_status_drift([item(1, "In Progress"), item(2, "Complete")], CONFIG)
        self.assertEqual(3, len(problems))

    def test_matching_state_is_clean(self):
        items = [item(1, "Complete"), item(2, "Backlog"), item(3, "Ready")]
        self.assertEqual([], bh.check_status_drift(items, CONFIG))

    def test_missing_area_is_a_required_field_gap(self):
        self.assertEqual(1, len(bh.check_required_fields([item(2, "Backlog", area=None)], CONFIG)))


class BoardSpelling(unittest.TestCase):
    """A board that names its columns "Done" and "In progress" and has no Work Type field."""
    CFG = {"repoOwner": "o", "repoName": "r", "fields": {"status": {"id": "F", "options": {
        "Backlog": "a", "Ready": "b", "In Progress": "c", "Complete": "d"}}}}
    LIVE = {"a": "Backlog", "b": "Ready", "c": "In progress", "d": "Done"}

    def test_finished_and_open_names_come_from_the_live_board(self):
        finished, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual("Done", finished)
        self.assertEqual({"Backlog", "Ready", "In progress"}, open_names)

    def test_extra_open_columns_stay_open(self):
        for keys, finished_key in ((["Todo", "In Progress", "Done"], "Done"),
                                   (["Backlog", "Ready", "In progress", "In review", "Done"], "Done")):
            cfg = {"fields": {"status": {"id": "F", "options": {k: k for k in keys}}}}
            finished, open_names = bh.resolve_statuses(cfg, {k: k for k in keys})
            self.assertEqual(finished_key, finished)
            self.assertEqual(set(keys) - {finished_key}, open_names)

    def test_done_on_a_closed_issue_is_clean(self):
        real = bh.run_gh
        bh.run_gh = lambda args: json.dumps([{"number": 1, "state": "CLOSED", "title": "t"}])
        try:
            self.assertEqual([], bh.check_status_drift([item(1, "Done")], self.CFG, "Done"))
        finally:
            bh.run_gh = real

    def test_work_type_is_not_required_when_the_board_has_no_such_field(self):
        it = item(2, "In progress")
        del it["work Type"]
        _, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual([], bh.check_required_fields([it], self.CFG, open_names))

    def test_in_progress_items_are_checked_under_the_board_spelling(self):
        it = item(2, "In progress")
        it["size"] = None
        _, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual(1, len(bh.check_required_fields([it], self.CFG, open_names)))


class DuplicateCards(unittest.TestCase):
    def test_two_cards_for_one_issue_are_reported_with_their_statuses(self):
        items = [item(1, "Backlog"), item(1, "Complete"), item(2, "Ready")]
        found = bh.check_duplicate_cards(items)
        self.assertEqual(["o/r#1: 2 cards (Backlog, Complete, conflicting Status)"], found)

    def test_one_card_per_issue_is_clean(self):
        self.assertEqual([], bh.check_duplicate_cards([item(1, "Ready"), item(2, "Ready")]))


class ReadyChecks(unittest.TestCase):
    def test_a_board_with_no_backlog_items_is_clean(self):
        items = [{"status": "Complete", "content": {"body": ""}}]
        self.assertEqual(bh.check_ready_occupancy(items), [])
        self.assertEqual(bh.check_ready_candidates(items), [])

    def test_backlog_items_with_an_empty_ready_column_are_flagged(self):
        items = [{"status": "Backlog", "priority": "P1", "size": "S",
                  "content": {"number": 1, "title": "Next", "body": ""}}]
        self.assertEqual(len(bh.check_ready_occupancy(items)), 1)
        self.assertTrue(bh.check_ready_candidates(items))


class FamilyDiscovery(unittest.TestCase):
    def test_every_top_level_folder_is_a_family_except_docs_and_dot_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("alpha", "beta", "docs", ".git"):
                (Path(tmp) / name).mkdir()
            (Path(tmp) / "README.md").write_text("x")
            self.assertEqual({"alpha", "beta"}, bh.discover_families(tmp))


class ConfigLoading(unittest.TestCase):
    def test_no_path_or_a_missing_file_exits_with_a_message_naming_the_flag(self):
        for path in (None, Path("/nonexistent/backlog-config.json")):
            with self.assertRaises(SystemExit) as raised:
                bh.load_config(path)
            self.assertIn("--config", str(raised.exception))

    def test_existing_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backlog-config.json"
            path.write_text(json.dumps(CONFIG))
            self.assertEqual(CONFIG, bh.load_config(path))


NOW = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)


def aged(status, days, priority="P1", labels=(), commented=True):
    when = (NOW - datetime.timedelta(days=days)).isoformat()
    it = item(1, status)
    it["priority"] = priority
    it["content"].update({"labels": list(labels), "created_at": when,
                          "last_comment_at": when if commented else None})
    return it


class Stale(unittest.TestCase):
    def test_backlog_p1_over_14_days_is_stale_and_p2_is_not(self):
        self.assertEqual(1, len(bh.check_stale([aged("Backlog", 15)], NOW)))
        self.assertEqual([], bh.check_stale([aged("Backlog", 13)], NOW))
        self.assertEqual([], bh.check_stale([aged("Backlog", 99, priority="P2")], NOW))

    def test_in_progress_over_7_days_is_stale_under_either_spelling(self):
        for name in ("In Progress", "In progress"):
            self.assertEqual(1, len(bh.check_stale([aged(name, 8)], NOW)))
        self.assertEqual([], bh.check_stale([aged("In Progress", 6)], NOW))

    def test_deferred_over_30_days_is_stale(self):
        self.assertEqual(1, len(bh.check_stale([aged("Ready", 31, labels=["deferred"])], NOW)))
        self.assertEqual([], bh.check_stale([aged("Ready", 29, labels=["deferred"])], NOW))

    def test_an_item_with_no_comment_counts_from_its_filing_date(self):
        self.assertEqual(1, len(bh.check_stale([aged("Backlog", 20, commented=False)], NOW)))

    def test_finished_items_are_never_stale(self):
        self.assertEqual([], bh.check_stale([aged("Complete", 200)], NOW))


class AreaPolicy(unittest.TestCase):
    def setUp(self):
        self.real = bh.run_gh
        graphql = {"data": {"node": {"options": [{"name": n} for n in ("alpha", "old", "parked", "any", "stray")]}}}
        bh.run_gh = lambda args: json.dumps(graphql)

    def tearDown(self):
        bh.run_gh = self.real

    def test_retired_parked_and_catch_all_come_from_the_config(self):
        cfg = {"fields": {"area": {"id": "A"}},
               "areaPolicy": {"retired": ["old"], "parked": ["parked"], "catchAll": ["any"]}}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "alpha").mkdir()
            found = bh.check_area_freshness(cfg, tmp)
        self.assertEqual(1, len(found))
        self.assertIn("'stray'", found[0])

    def test_a_config_without_a_policy_treats_every_extra_option_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "alpha").mkdir()
            found = bh.check_area_freshness({"fields": {"area": {"id": "A"}}}, tmp)
        self.assertEqual(4, len(found))


class IssueDetails(unittest.TestCase):
    def setUp(self):
        self.real = bh.run_gh
        self.calls = []

    def tearDown(self):
        bh.run_gh = self.real

    def test_reads_every_board_repo_with_pagination_and_fills_details(self):
        def fake(args):
            self.calls.append(args)
            if "issues/comments" in args[2]:
                return ('{"issue": 1, "at": "2026-10-01T00:00:00Z"}\n'
                        '{"issue": 1, "at": "2026-10-05T00:00:00Z"}\n')
            return '{"number": 1, "body": "b", "created_at": "2026-09-01T00:00:00Z", "labels": ["deferred"]}\n'
        bh.run_gh = fake
        it = item(1, "Backlog")
        bh.fetch_issue_details({"repoOwner": "o", "repoName": "r"}, [it])
        self.assertTrue(all(c[:2] == ["api", "--paginate"] for c in self.calls))
        c = it["content"]
        self.assertEqual(("b", ["deferred"], "2026-10-05T00:00:00Z"), (c["body"], c["labels"], c["last_comment_at"]))

    def test_the_same_issue_number_in_two_repos_keeps_its_own_body(self):
        def fake(args):
            if "issues/comments" in args[2]:
                return ""
            body = "mine" if "/o/r/" in args[2] or "repos/o/r/" in args[2] else "other"
            return '{"number": 1, "body": "%s", "created_at": "2026-09-01T00:00:00Z", "labels": []}\n' % body
        bh.run_gh = fake
        mine, other = item(1, "Backlog"), item(1, "Backlog")
        other["content"]["repository"] = "x/y"
        bh.fetch_issue_details({"repoOwner": "o", "repoName": "r"}, [mine, other])
        self.assertEqual(("mine", "other"), (mine["content"]["body"], other["content"]["body"]))

    def test_a_board_at_the_list_limit_stops_the_run(self):
        bh.run_gh = lambda args: json.dumps({"items": [{}] * bh.ITEM_LIMIT})
        with self.assertRaises(SystemExit) as raised:
            bh.load_items({"projectNumber": 1, "projectOwner": "o"})
        self.assertIn("limit", str(raised.exception))


class ForkGuard(unittest.TestCase):
    REAL = {"repoOwner": "owner", "repoName": "Repo", "projectNumber": 1, "projectId": "PVT_x", "fields": {}}

    def repo(self, tmp, origin):
        subprocess.run(["git", "init", "-q", tmp], check=True)
        subprocess.run(["git", "-C", tmp, "remote", "add", "origin", origin], check=True)

    def write(self, tmp, config):
        path = Path(tmp) / "backlog-config.json"
        path.write_text(json.dumps(config))
        return path

    def test_a_config_for_another_owners_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, "https://github.com/someone-else/Repo.git")
            with self.assertRaises(SystemExit) as raised:
                bh.load_config(self.write(tmp, self.REAL))
        self.assertIn("fork", str(raised.exception))
        self.assertIn("backlog-config.example.json", str(raised.exception))

    def test_the_owners_own_checkout_loads_over_https_and_ssh(self):
        for origin in ("https://github.com/owner/Repo.git", "git@github.com:owner/repo.git"):
            with tempfile.TemporaryDirectory() as tmp:
                self.repo(tmp, origin)
                self.assertEqual(self.REAL, bh.load_config(self.write(tmp, self.REAL)))

    def test_the_example_is_refused_as_a_live_config(self):
        example = Path(__file__).resolve().parents[3] / "shared" / "backlog-config.example.json"
        with self.assertRaises(SystemExit) as raised:
            bh.load_config(example)
        self.assertIn("placeholder", str(raised.exception))

    def test_a_missing_config_message_names_the_example(self):
        with self.assertRaises(SystemExit) as raised:
            bh.load_config(Path("/nonexistent/backlog-config.json"))
        self.assertIn("shared/backlog-config.example.json", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
