"""A launcher inside a path the local config lists as live fails conform and install, naming the agent copy."""

import json
import os
import unittest
from unittest import mock

from _support import load_script, quiet, temp_dir

load_script("scripts/olivercode", "olivercode_launcher_live")
from lib import cmd_install, live_copy  # noqa: E402


class TestLiveCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-live-")
        self.live = self.tmp / "bot"
        self.agent = self.tmp / "bot-agent"
        self.live.mkdir()
        self.agent.mkdir()
        config = self.tmp / "local.json"
        config.write_text(json.dumps({"liveCopies": {str(self.live): str(self.agent)}}))
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(config)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_launcher_in_a_live_path_fails_and_names_the_agent_copy(self):
        found = live_copy.problem(self.live / "OliverCode")
        self.assertIn(str(self.agent), found)
        self.assertIn(str(self.live.resolve()), found)

    def test_the_agent_copy_and_other_paths_pass(self):
        self.assertEqual("", live_copy.problem(self.agent))
        self.assertEqual("", live_copy.problem(self.tmp / "elsewhere"))

    def test_no_live_list_passes(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": os.devnull}):
            self.assertEqual("", live_copy.problem(self.live))

    def test_install_refuses_and_writes_nothing(self):
        home = self.tmp / "home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            code, _ = quiet(cmd_install.command_install, self.live)
        self.assertEqual(1, code)
        self.assertFalse((home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
