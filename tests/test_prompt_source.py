"""Only the owner types a prompt: a message from another session or the system is not the owner's."""

import sys
import unittest

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import prompt_source  # noqa: E402


class TestFromOwner(unittest.TestCase):
    def test_only_the_owner_types_a_prompt(self):
        for text in ("<task-notification>never do that again</task-notification>", "<side-sessions-event>wrong</side-sessions-event>"):
            self.assertFalse(prompt_source.from_owner(text))
        self.assertTrue(prompt_source.from_owner("never do that"))


if __name__ == "__main__":
    unittest.main()
