import json
import unittest

import board_rest as br

ITEM = {
    "archived_at": None, "content_type": "Issue", "content": {"number": 7, "title": "A story", "state": "open"},
    "fields": [
        {"name": "Title", "data_type": "title", "value": {"raw": "A story"}},
        {"name": "Status", "data_type": "single_select", "value": {"name": {"raw": "Ready"}}},
        {"name": "Work Type", "data_type": "single_select", "value": {"name": {"raw": "Story"}}},
        {"name": "Area", "data_type": "single_select", "value": None},
        {"name": "Repository", "data_type": "repository", "value": {"full_name": "o/r"}},
    ],
}


def lines(*objects):
    return "\n".join(json.dumps(o) for o in objects)


class Shape(unittest.TestCase):
    def test_an_item_is_shaped_like_the_gh_item_list(self):
        got = br.shape(ITEM)
        self.assertEqual("Ready", got["status"])
        self.assertEqual("Story", got["work Type"])
        self.assertIsNone(got["area"])
        self.assertEqual({"number": 7, "title": "A story", "type": "Issue", "repository": "o/r"}, got["content"])


class ProjectItems(unittest.TestCase):
    CFG = {"projectOwner": "o", "projectNumber": 3}

    def test_it_reads_fields_then_items_and_skips_archived_ones(self):
        calls = []

        def run(args):
            calls.append(args)
            if "fields?per_page=100" in args[3]:
                return lines({"id": 11, "name": "Status"}, {"id": 12, "name": "Assignees"})
            return lines(ITEM, {**ITEM, "archived_at": "2026-01-01"})

        items = br.project_items(self.CFG, run)
        self.assertEqual(1, len(items))
        self.assertIn("fields=11", calls[1][3])
        self.assertNotIn("12", calls[1][3].split("fields=")[1])

    def test_a_field_name_spelled_with_other_capitals_is_read(self):
        calls = []

        def run(args):
            calls.append(args)
            if "fields?per_page=100" in args[3]:
                return lines({"id": 13, "name": "Work type"})
            return lines(ITEM)

        br.project_items(self.CFG, run)
        self.assertIn("fields=13", calls[1][3])

    def test_a_user_path_that_fails_falls_to_the_organization_path(self):
        seen = []

        def run(args):
            seen.append(args[3].split("/")[0])
            if args[3].startswith("users/"):
                return None
            return lines({"id": 1, "name": "Status"}) if "fields?" in args[3] else lines(ITEM)

        self.assertEqual(1, len(br.project_items(self.CFG, run)))
        self.assertEqual(["users", "orgs", "orgs"], seen)

    def test_a_board_rest_cannot_read_returns_none(self):
        self.assertIsNone(br.project_items(self.CFG, lambda args: None))


class RepoIssues(unittest.TestCase):
    def test_state_is_spelled_the_way_gh_issue_list_spells_it(self):
        got = br.repo_issues("o/r", lambda args: lines({"number": 1, "state": "open", "title": "x"}))
        self.assertEqual([{"number": 1, "state": "OPEN", "title": "x"}], got)

    def test_a_failed_read_returns_none(self):
        self.assertIsNone(br.repo_issues("o/r", lambda args: None))


if __name__ == "__main__":
    unittest.main()
