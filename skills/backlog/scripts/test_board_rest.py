import json
from urllib.parse import parse_qs, urlparse
import unittest

import board_rest as br

ITEM = {
    "archived_at": None, "content_type": "Issue", "content": {"number": 7, "title": "A story", "state": "open",
                                                                  "repository_url": "https://api.github.com/repos/o/r"},
    "fields": [
        {"name": "Status", "data_type": "single_select", "value": {"name": {"raw": "Ready"}}},
        {"name": "Work Type", "data_type": "single_select", "value": {"name": {"raw": "Story"}}},
    ],
}


def page(*objects):
    return "HTTP/2.0 200 OK\n\n" + json.dumps(list(objects))


def lines(*objects):
    return "\n".join(json.dumps(o) for o in objects)


class Shape(unittest.TestCase):
    def test_an_item_is_shaped_like_the_gh_item_list(self):
        got = br.shape(ITEM)
        self.assertEqual("Ready", got["status"])
        self.assertEqual("Story", got["work Type"])
        self.assertEqual({"number": 7, "title": "A story", "type": "Issue", "repository": "o/r"}, got["content"])


class ProjectItems(unittest.TestCase):
    CFG = {"projectOwner": "o", "projectNumber": 3}

    def test_it_reads_fields_then_items_and_skips_archived_ones(self):
        calls = []

        def run(args):
            calls.append(args)
            if "fields?per_page=100" in args[3]:
                return lines({"id": 11, "name": "Status"}, {"id": 12, "name": "Assignees"})
            return page(ITEM, {**ITEM, "archived_at": "2026-01-01"})

        items = br.project_items(self.CFG, run)
        self.assertEqual(1, len(items))
        self.assertIn("fields=11", calls[1][-1])
        self.assertEqual("A story", items[0]["title"])
        self.assertEqual("o/r", items[0]["content"]["repository"])
        self.assertNotIn("12", calls[1][-1].split("fields=")[1])

    def test_a_field_name_spelled_with_other_capitals_is_read(self):
        calls = []

        def run(args):
            calls.append(args)
            if "fields?per_page=100" in args[3]:
                return lines({"id": 13, "name": "Work type"})
            return page(ITEM)

        br.project_items(self.CFG, run)
        self.assertIn("fields=13", calls[1][-1])

    def test_an_area_field_on_an_old_board_is_not_asked_for(self):
        calls = []

        def run(args):
            calls.append(args)
            if "fields?per_page=100" in args[3]:
                return lines({"id": 11, "name": "Status"}, {"id": 14, "name": "Area"})
            return page(ITEM)

        br.project_items(self.CFG, run)
        self.assertIn("fields=11", calls[1][-1])
        self.assertNotIn("14", calls[1][-1].split("fields=")[1])

    def test_a_user_path_that_fails_falls_to_the_organization_path(self):
        seen = []

        def run(args):
            url = next(a for a in args if "projectsV2" in a)
            seen.append(url.split("/")[0])
            if url.startswith("users/"):
                return None
            return lines({"id": 1, "name": "Status"}) if "fields?" in url else page(ITEM)

        self.assertEqual(1, len(br.project_items(self.CFG, run)))
        self.assertEqual(["users", "orgs", "orgs"], seen)

    def paged(self, fail):
        """A runner serving 150 items by `after` cursor (the index to resume at); `fail(size, after)` says which item
        pages answer None."""
        calls = []

        def run(args):
            if "fields?" in args[3]:
                return lines({"id": 1, "name": "Status"})
            query = parse_qs(urlparse(args[4]).query)
            size, after = int(query["per_page"][0]), int(query.get("after", ["0"])[0])
            calls.append((size, after))
            if fail(size, after):
                return None
            rows = [{**ITEM, "content": {"number": n}} for n in range(150)][after:after + size]
            link = f'Link: <https://api.github.com/x?per_page={size}&after={after + size}>; rel="next"\n' \
                if after + size < 150 else ""
            return f"HTTP/2.0 200 OK\n{link}\n" + json.dumps(rows)
        return run, calls

    def test_a_failed_page_is_read_again_as_a_smaller_page(self):
        run, calls = self.paged(lambda size, after: size == 100 and after == 100)
        items = br.project_items(self.CFG, run)
        self.assertEqual(list(range(150)), [i["content"]["number"] for i in items])
        self.assertEqual([(100, 0), (100, 100), (25, 100), (100, 125)], calls)

    def test_a_page_that_fails_after_the_retry_gives_none(self):
        run, _ = self.paged(lambda size, after: after == 100)
        self.assertIsNone(br.project_items(self.CFG, run))

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
