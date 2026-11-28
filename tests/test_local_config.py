"""Tests for scripts/lib/local_config.py: machine paths stay out of tracked files."""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _support import temp_dir  # noqa: E402
from lib import cmd_install, local_config  # noqa: E402


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


class ConvergeLocalConfig(unittest.TestCase):
    """#1295: install leaves the local file with the keys this version reads, each repo once, and repo paths that exist."""

    def setUp(self):
        self.root = temp_dir(self)
        self.file = self.root / "olivercode.local.json"
        self.fleet = self.root / "repos"
        self.fleet.mkdir()
        self.home = self.root / "home"
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.file), "OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        self.file.write_text(json.dumps(data))

    def read(self):
        return json.loads(self.file.read_text())

    def checkout(self, name, origin):
        path = self.fleet / name
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", f"https://github.com/me/{origin}.git"], check=True)
        return path

    def test_the_owner_zone_shows_its_daylight_abbreviation(self):
        """#1386: local_time formats in the owner's timeZone, with the abbreviation that zone has at that time."""
        self.write({"timeZone": "America/Los_Angeles"})
        self.assertEqual("05:00 PDT", local_config.local_time(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)))

    def test_no_time_zone_set_shows_new_york_in_winter(self):
        self.write({})
        self.assertEqual("07:00 EST", local_config.local_time(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)))

    def test_a_zone_the_database_does_not_hold_falls_back_to_new_york(self):
        self.write({"timeZone": "Mars/Olympus"})
        self.assertEqual("07:00 EST", local_config.local_time(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)))

    def test_a_key_the_version_no_longer_reads_is_removed_once_backed_up_and_named(self):
        self.write({"pushRepos": ["old"], "maxBuilders": 3, "repoRoot": str(self.fleet)})
        lines = cmd_install._converge_local_config()
        self.assertEqual(self.read(), {"maxBuilders": 3, "repoRoot": str(self.fleet)})
        self.assertTrue(any(line.startswith("[REMOVED] pushRepos") for line in lines), lines)
        backups = list((self.home / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["pushRepos"], ["old"])

    def test_a_value_the_user_chose_is_kept(self):
        self.write({"maxBuilders": 3, "repoRoot": str(self.fleet)})
        self.assertEqual(cmd_install._converge_local_config(), [])
        self.assertEqual(self.read(), {"maxBuilders": 3, "repoRoot": str(self.fleet)})

    def test_a_repo_that_moved_points_at_its_checkout_and_one_with_no_checkout_is_removed(self):
        moved = self.checkout("alpha", "alpha")
        self.write({"repoRoot": str(self.fleet), "repoPaths": {"alpha": str(self.root / "gone-alpha"), "beta": str(self.root / "gone-beta")}})
        lines = cmd_install._converge_local_config()
        self.assertEqual(self.read()["repoPaths"], {"alpha": str(moved)})
        self.assertTrue(any(line.startswith("[REMOVED] repoPaths.beta") for line in lines), lines)
        self.assertTrue(any(line.startswith("[MOVED] repoPaths.alpha") for line in lines), lines)

    def test_a_list_names_each_repo_once(self):
        self.write({"repoRoot": str(self.fleet), "otherDeviceRepos": ["my-repo", "other", "My-repo"]})
        lines = cmd_install._converge_local_config()
        self.assertEqual(self.read()["otherDeviceRepos"], ["my-repo", "other"])
        self.assertTrue(any(line.startswith("[DEDUPED] otherDeviceRepos") for line in lines), lines)

    def test_a_second_run_changes_nothing_and_writes_no_backup(self):
        self.write({"pushRepos": [], "repoRoot": str(self.fleet)})
        cmd_install._converge_local_config()
        self.assertEqual(cmd_install._converge_local_config(), [])
        self.assertEqual(len(list((self.home / "backups").iterdir())), 1)
