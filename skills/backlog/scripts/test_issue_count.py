import json
import subprocess
import unittest

import issue_count as ic


def fake(pages, code=0):
    calls = []

    def runner(args):
        calls.append(args)
        return subprocess.CompletedProcess([], code, json.dumps(pages), "")
    return runner, calls


class IssueCount(unittest.TestCase):
    def test_a_fixture_page_of_three_issues_counts_three_and_leaves_out_pull_requests(self):
        runner, calls = fake([[{"number": 1}, {"number": 2}, {"number": 3}, {"number": 4, "pull_request": {}}]])
        self.assertEqual(3, ic.count_issues("o/r", "open", runner))
        self.assertIn("repos/o/r/issues", calls[0])
        self.assertNotIn("search", " ".join(calls[0]))

    def test_pages_add_up_and_a_failed_read_is_none(self):
        runner, _ = fake([[{"number": 1}], [{"number": 2}]])
        self.assertEqual(2, ic.count_issues("o/r", "closed", runner))
        self.assertIsNone(ic.count_issues("o/r", "open", fake([], code=1)[0]))
        self.assertEqual(2, ic.main([]))


if __name__ == "__main__":
    unittest.main()
