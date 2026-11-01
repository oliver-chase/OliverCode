"""Test the status-drift, required-field, duplicate-card, family-discovery and config-loading checks.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import json
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


if __name__ == "__main__":
    unittest.main()
