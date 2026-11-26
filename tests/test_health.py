"""Acceptance checks for the GitHub access prerequisite used by install (#994)."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import load_script, temp_dir

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
load_script("scripts/lib/cmd_health.py", "cmd_health_for_names")
from lib import cmd_health, health_checks, health_env  # noqa: E402


class TestGithubProjectAccess(unittest.TestCase):
    def test_missing_project_scope_names_the_refresh_command(self):
        result = subprocess.CompletedProcess(["gh", "auth", "status"], 0, "", "Token scopes: 'repo'")
        with mock.patch.object(health_env, "_gh_auth_status", return_value=result):
            self.assertEqual("gh is signed in without the project scope. Run: gh auth refresh -s project", health_checks.gh_ready())

    def test_project_scope_is_sufficient_without_a_graphql_call(self):
        result = subprocess.CompletedProcess(["gh", "auth", "status"], 0, "", "Token scopes: 'project', 'repo'")
        with mock.patch.object(health_env, "_gh_auth_status", return_value=result) as status:
            self.assertEqual("", health_checks.gh_ready())
        status.assert_called_once_with()


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
