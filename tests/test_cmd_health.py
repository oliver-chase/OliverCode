"""Tests for the repo-name check in scripts/lib/cmd_health.py: folder, GitHub and registry names agree or the owner is asked once (#1034)."""

import json
import os
import unittest
from pathlib import Path
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

    def test_mismatch_is_found(self):
        self.assertEqual(cmd_health.repo_names_mismatches(self.profiles, self.root), [("registry-name", "folder-name", "github-name")])

    def test_agreeing_names_are_not_asked(self):
        with mock.patch.object(cmd_health._repo_state, "origin", lambda path: "owner/folder-name"), \
             mock.patch.object(cmd_health, "_iter_fleet", lambda *a, **k: [("folder-name", {}, self.root / "folder-name")]):
            lines = []
            result = cmd_health.repo_names_check(self.profiles, self.root, interactive=True, out=lines.append)
        self.assertEqual(result, (1, 0, 0))
        self.assertIn("agree", lines[0])

    def test_asks_shows_both_names_and_records_answer(self):
        lines = []
        replies = iter(["maybe", "GitHub"])
        result = cmd_health.repo_names_check(self.profiles, self.root, ask=lambda _: next(replies), interactive=True, out=lines.append)
        self.assertEqual(result, (1, 0, 0))
        self.assertIn("'folder-name'", lines[0])
        self.assertIn("'github-name'", lines[0])
        saved = json.loads(self.local.read_text())
        self.assertEqual(saved["other"], 1)
        self.assertEqual(saved["repoNames"]["registry-name"], {"folder": "folder-name", "github": "github-name", "keep": "github"})

    def test_answered_mismatch_is_not_asked_again(self):
        cmd_health.repo_names_record("registry-name", "folder-name", "github-name", "folder")
        asked = []
        result = cmd_health.repo_names_check(self.profiles, self.root, ask=asked.append, interactive=True, out=lambda _: None)
        self.assertEqual(asked, [])
        self.assertEqual(result, (1, 0, 0))

    def test_changed_names_ask_again(self):
        cmd_health.repo_names_record("registry-name", "old-folder", "github-name", "folder")
        self.assertIsNone(cmd_health.repo_names_answered("registry-name", "folder-name", "github-name"))

    def test_not_interactive_warns_without_asking(self):
        lines = []
        result = cmd_health.repo_names_check(self.profiles, self.root, ask=lambda _: self.fail("asked"), interactive=False, out=lines.append)
        self.assertEqual(result, (0, 0, 1))
        self.assertTrue(any("WARN" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
