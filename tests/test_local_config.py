"""Tests for scripts/lib/local_config.py: machine paths stay out of tracked files."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _support import temp_dir  # noqa: E402
from lib import local_config  # noqa: E402


class LocalConfig(unittest.TestCase):
    def setUp(self):
        self.file = temp_dir(self) / "olivercode.local.json"
        patcher = mock.patch.object(local_config, "LOCAL_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("OLIVERCODE_SKILLS_ROOT", "OLIVERCODE_LOCAL_CONFIG"):
            os.environ.pop(key, None)

    def write(self, data):
        self.file.write_text(json.dumps(data))

    def test_the_builder_limit_follows_cores_and_memory_unless_the_owner_sets_it(self):
        """#1055: half the cores or the memory in GB less 4, whichever is smaller, and never below 1."""
        self.assertEqual(4, local_config.default_builders(cores=8, mem_gb=8))
        self.assertEqual(8, local_config.default_builders(cores=16, mem_gb=32))
        self.assertEqual(1, local_config.default_builders(cores=2, mem_gb=4))
        with mock.patch.object(local_config, "default_builders", return_value=4):
            self.write({"maxBuilders": 6})
            self.assertEqual(6, local_config.max_builders())
            for bad in (0, -2, "four", True, 2.5):
                self.write({"maxBuilders": bad})
                self.assertEqual(4, local_config.max_builders(), bad)

    def test_unset_means_this_machine_has_none(self):
        self.assertEqual(local_config.private_repos(), {})
        self.assertIsNone(local_config.skills_root())
        self.assertEqual(local_config.repo_paths(), {})

    def test_the_file_supplies_paths_with_tilde_expanded(self):
        self.write({"privateRepos": {"notes": "~/v"}, "skillsRoot": "/s"})
        self.assertEqual(local_config.private_repos(), {"notes": Path.home() / "v"})
        self.assertEqual(local_config.skills_root(), Path("/s"))

    def test_the_skills_root_environment_variable_wins_over_the_file(self):
        self.write({"skillsRoot": "/from-file"})
        os.environ["OLIVERCODE_SKILLS_ROOT"] = "/from-env"
        self.assertEqual(local_config.skills_root(), Path("/from-env"))

    def test_the_config_variable_names_another_file_and_devnull_reads_nothing(self):
        self.write({"privateRepos": {"notes": "/real/notes"}})
        other = self.file.parent / "other.json"
        other.write_text(json.dumps({"skillsRoot": "/s2"}))
        os.environ["OLIVERCODE_LOCAL_CONFIG"] = str(other)
        self.assertEqual((local_config.skills_root(), local_config.private_repos()), (Path("/s2"), {}))
        os.environ["OLIVERCODE_LOCAL_CONFIG"] = os.devnull
        self.assertEqual((local_config.skills_root(), local_config.private_repos()), (None, {}))

    def test_repo_paths_expand_a_tilde(self):
        self.write({"repoPaths": {"alpha": "~/work/alpha"}})
        self.assertEqual(local_config.repo_paths(), {"alpha": Path.home() / "work" / "alpha"})
