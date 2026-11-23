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


if __name__ == "__main__":
    unittest.main()
