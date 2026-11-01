"""Tests for scripts/lib/local_config.py: machine paths stay out of tracked files."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import local_config  # noqa: E402
from lib.repo_profiles import resolve_repo_path  # noqa: E402


class LocalConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "olivercode.local.json"
        patcher = mock.patch.object(local_config, "LOCAL_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("OLIVERCODE_VAULT_ROOT", "OLIVERCODE_SKILLS_ROOT"):
            os.environ.pop(key, None)

    def write(self, data):
        self.file.write_text(json.dumps(data))

    def test_unset_means_this_machine_has_none(self):
        self.assertEqual(local_config.private_repos(), {})
        self.assertIsNone(local_config.skills_root())
        self.assertEqual(local_config.repo_paths(), {})
        self.assertEqual(local_config.push_repos(), [])

    def test_the_file_supplies_paths_with_tilde_expanded(self):
        self.write({"privateRepos": {"notes": "~/v"}, "skillsRoot": "/s", "pushRepos": ["a"]})
        self.assertEqual(local_config.private_repos(), {"notes": Path.home() / "v"})
        self.assertEqual(local_config.skills_root(), Path("/s"))
        self.assertEqual(local_config.push_repos(), ["a"])

    def test_environment_wins_over_the_file(self):
        self.write({"vaultRoot": "/from-file"})
        os.environ["OLIVERCODE_VAULT_ROOT"] = "/from-env"
        self.assertEqual(local_config.private_repos(), {"vault": Path("/from-env")})

    def test_a_machine_set_up_with_the_old_vault_setting_keeps_working(self):
        self.write({"vaultRoot": "~/old", "privateRepos": {"notes": "/n"}})
        self.assertEqual(local_config.private_repos(), {"notes": Path("/n"), "vault": Path.home() / "old"})

    def test_the_skills_root_environment_variable_wins_over_the_file(self):
        self.write({"skillsRoot": "/from-file"})
        os.environ["OLIVERCODE_SKILLS_ROOT"] = "/from-env"
        self.assertEqual(local_config.skills_root(), Path("/from-env"))

    def test_a_vault_named_in_private_repos_wins_over_the_old_vault_setting(self):
        self.write({"vaultRoot": "/old", "privateRepos": {"vault": "/new"}})
        self.assertEqual(local_config.private_repos(), {"vault": Path("/new")})
        os.environ["OLIVERCODE_VAULT_ROOT"] = "/from-env"
        self.assertEqual(local_config.private_repos(), {"vault": Path("/new")})

    def test_repo_paths_expand_a_tilde(self):
        self.write({"repoPaths": {"alpha": "~/work/alpha"}})
        self.assertEqual(local_config.repo_paths(), {"alpha": Path.home() / "work" / "alpha"})

    def test_a_local_repo_path_wins_over_the_profile_and_the_sibling_default(self):
        self.write({"repoPaths": {"alpha": "/this/machine/alpha"}})
        got = resolve_repo_path("alpha", {"path": "sub/alpha"}, Path("/fleet"))
        self.assertEqual(got, Path("/this/machine/alpha"))
        self.assertEqual(resolve_repo_path("beta", {}, Path("/fleet")), Path("/fleet/beta"))


if __name__ == "__main__":
    unittest.main()
