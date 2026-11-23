"""A scratch HOME and checkout the launcher fleet-command tests share."""

import os
import unittest
from unittest import mock

from _support import temp_dir


class ScratchHome(unittest.TestCase):
    """A scratch HOME and checkout that no test can leave behind."""

    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-fleetcmd-", resolve=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.oc = self.tmp / "oc"
        self.oc.mkdir()

    def add_skill(self, name, description="Does a thing."):
        folder = self.oc / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: "{description}"\n---\n\nBody.\n', encoding="utf-8")
        return folder
