"""A lesson with no id is matched by no failure reason (#1039)."""

import sys
import unittest

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import lesson_cover  # noqa: E402


class TestRepeats(unittest.TestCase):
    def test_a_lesson_with_no_id_matches_no_failure_by_id(self):
        rows = [("2026-01-02T00:00:00", "r", "gate", "some reason")]
        self.assertFalse(lesson_cover.repeats({"rule": ""}, "2026-01-01", rows))
        self.assertTrue(lesson_cover.repeats({"id": "L1", "rule": ""}, "2026-01-01", [("2026-01-02T00:00:00", "r", "gate", "see L1")]))

    def test_a_linked_story_is_not_verified_until_complete_story_records_implementation(self):
        from datetime import date
        linked = {"id": "L1", "rule": "retry after API errors", "covered_by": "#1147", "covered_on": "2026-01-01"}
        self.assertFalse(lesson_cover.verified(linked, date(2026, 3, 1), []))
        implemented = {**linked, "implemented_by": "abc1234", "implemented_on": "2026-01-01"}
        self.assertTrue(lesson_cover.verified(implemented, date(2026, 3, 1), []))
        self.assertFalse(lesson_cover.verified(implemented, date(2026, 3, 1),
                                               [("2026-02-01T00:00:00Z", "r", "gate", "retry after API errors failed again")]))


if __name__ == "__main__":
    unittest.main()
