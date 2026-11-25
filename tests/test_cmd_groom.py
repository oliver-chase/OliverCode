"""The word leak is not a security story (#1039)."""

import sys
import unittest

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_groom  # noqa: E402


class TestPriority(unittest.TestCase):
    def test_the_word_leak_is_not_a_security_story_but_a_leaked_key_is(self):
        self.assertEqual("P2", cmd_groom.priority_of({"title": "Fix a memory leak in the cache", "body": ""}))
        self.assertEqual("P0", cmd_groom.priority_of({"title": "A leaked token in the log", "body": ""}))
        self.assertEqual("P0", cmd_groom.priority_of({"title": "Keys leaked in the log", "body": ""}))


class TestSize(unittest.TestCase):
    def test_a_stated_small_size_is_raised_to_match_a_wide_files_area(self):
        files = "\\n".join(f"  - scripts/file_{i}.py" for i in range(19))
        story = {"body": f"Size: XS\\n\\nFiles area:\\n{files}\\n"}
        self.assertEqual("XL", cmd_groom.size_of(story))

    def test_a_stated_size_that_covers_the_files_area_is_preserved(self):
        story = {"body": "Size: M\\n\\nFiles area:\\n  - scripts/a.py\\n"}
        self.assertEqual("M", cmd_groom.size_of(story))

    def test_ready_card_size_is_raised_but_backlog_card_is_not_rewritten(self):
        story = {"body": "Size: XS\\n\\nFiles area:\\n" + "\\n".join(f"  - scripts/f{i}.py" for i in range(9))}
        items = [{"content": {"number": 42}, "size": "XS", "status": "Ready"}]
        ready = cmd_groom.filled(items, {42: story}, [])
        self.assertEqual("L", ready[0]["fields"]["size"])
        items[0]["status"] = "Backlog"
        backlog = cmd_groom.filled(items, {42: story}, [])
        self.assertNotIn("size", backlog[0]["fields"])

    def test_a_missing_board_size_is_filled_even_when_the_story_is_not_ready(self):
        story = {"body": "Size: S\\n\\nFiles area:\\n  - scripts/a.py"}
        items = [{"content": {"number": 43}, "size": "", "status": "Backlog"}]
        result = cmd_groom.filled(items, {43: story}, [])
        self.assertEqual("S", result[0]["fields"]["size"])


if __name__ == "__main__":
    unittest.main()
