"""scripts/lib/skill_links.py: one classification of the links in a skills folder."""

import sys
import unittest

from _support import temp_dir
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.skill_links import broken_links, link_state, link_states  # noqa: E402


class TestSkillLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-links-")
        self.skills = self.tmp / "skills"
        self.links = self.tmp / "links"
        for name in ("a", "b"):
            (self.skills / name).mkdir(parents=True)
        self.links.mkdir()

    def test_each_state_is_named(self):
        (self.links / "ok").symlink_to(self.skills / "a")
        (self.links / "elsewhere").symlink_to(self.skills / "b")
        (self.links / "broken").symlink_to(self.tmp / "gone")
        (self.links / "real").mkdir()
        expected = self.skills / "a"
        self.assertEqual("ok", link_state(self.links / "ok", expected))
        self.assertEqual("elsewhere", link_state(self.links / "elsewhere", expected))
        self.assertEqual("broken", link_state(self.links / "broken", expected))
        self.assertEqual("real", link_state(self.links / "real", expected))
        self.assertEqual("absent", link_state(self.links / "none", expected))

    def test_link_states_takes_the_expected_links(self):
        (self.links / "a").symlink_to(self.skills / "a")
        states = link_states({"a": self.skills / "a", "b": self.skills / "b"}, self.links)
        self.assertEqual({"a": "ok", "b": "absent"}, states)

    def test_broken_links_lists_only_dangling_links_sorted(self):
        (self.links / "z").symlink_to(self.tmp / "gone")
        (self.links / "y").symlink_to(self.tmp / "gone")
        (self.links / "fine").symlink_to(self.skills / "a")
        self.assertEqual(["y", "z"], broken_links(self.links))
