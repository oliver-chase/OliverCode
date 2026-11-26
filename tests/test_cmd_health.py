"""Tests for reporting local folder, GitHub and registry names without prompting (#1034)."""

import json
import os
import unittest
from unittest import mock

from _support import load_script, temp_dir

load_script("scripts/lib/cmd_health.py", "cmd_health_for_names")
from lib import cmd_health  # noqa: E402


class RepoNames(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self, resolve=True)
        (self.root / "folder-name" / ".git").mkdir(parents=True)
        self.local = self.root / "local.json"
        self.local.write_text(json.dumps({"other": 1}))
        env = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.local)})
        env.start()
        self.addCleanup(env.stop)
        self.profiles = {"registry-name": {}}
        fleet = mock.patch.object(cmd_health, "_iter_fleet", lambda *a, **k: [("registry-name", {}, self.root / "folder-name")])
        fleet.start()
        self.addCleanup(fleet.stop)
        origin = mock.patch.object(cmd_health._repo_state, "origin", lambda path: "owner/github-name")
        origin.start()
        self.addCleanup(origin.stop)

    def test_mismatch_is_reported_as_information_not_a_decision(self):
        lines = []
        result = cmd_health.repo_names_check(self.profiles, self.root, out=lines.append)
        self.assertEqual(result, (1, 0, 0))
        self.assertIn("local folder 'folder-name'", lines[0])
        self.assertIn("GitHub repo 'github-name'", lines[0])
        self.assertIn("Both names are kept", lines[0])
        self.assertIn("no rename is needed", lines[0])

    def test_mismatch_never_prompts_or_writes_a_choice(self):
        before = self.local.read_text()
        lines = []
        result = cmd_health.repo_names_check(self.profiles, self.root, out=lines.append)
        self.assertEqual(result, (1, 0, 0))
        self.assertEqual(self.local.read_text(), before)

    def test_agreeing_names_are_reported(self):
        with mock.patch.object(cmd_health._repo_state, "origin", lambda path: "owner/folder-name"), \
             mock.patch.object(cmd_health, "_iter_fleet", lambda *a, **k: [("folder-name", {}, self.root / "folder-name")]):
            lines = []
            result = cmd_health.repo_names_check(self.profiles, self.root, out=lines.append)
        self.assertEqual(result, (1, 0, 0))
        self.assertIn("agree", lines[0])


if __name__ == "__main__":
    unittest.main()
