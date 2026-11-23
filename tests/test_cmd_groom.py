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


if __name__ == "__main__":
    unittest.main()
