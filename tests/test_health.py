"""Acceptance checks for the GitHub access prerequisite used by install (#994)."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import health_checks, health_env  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
