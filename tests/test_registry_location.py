"""The fleet registry is read from a private repo when this checkout names one.

The tracked shared/ registry ships as an empty example so a fork carries no operator data.
A checkout that names a private repo holding olivercode/repo-profiles.json must read that
copy, or every fleet command would silently see an empty fleet.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _support import temp_dir  # noqa: E402
from lib import local_config, repo_profiles  # noqa: E402


class RegistryLocation(unittest.TestCase):
    def setUp(self):
        self.private = temp_dir(self) / "private"
        (self.private / "olivercode").mkdir(parents=True)
        (self.private / "olivercode" / "repo-profiles.json").write_text(json.dumps({"profiles": {"real": {}}}))
        p = mock.patch.object(repo_profiles, "private_repos", lambda: {"notes": self.private})
        p.start()
        self.addCleanup(p.stop)

    def test_this_checkout_reads_the_private_repos_copy(self):
        profiles, path = repo_profiles.load_repo_profiles(local_config.OC_ROOT)
        self.assertEqual((list(profiles), path), (["real"], self.private / "olivercode" / "repo-profiles.json"))

    def test_another_root_reads_its_own_shared_copy(self):
        other = self.private.parent / "fork"
        (other / "shared").mkdir(parents=True)
        (other / "shared" / "repo-profiles.json").write_text(json.dumps({"profiles": {}}))
        self.assertEqual(repo_profiles.registry_file(other), other / "shared" / "repo-profiles.json")

    def test_a_private_repo_without_a_registry_falls_back_to_the_tracked_example(self):
        (self.private / "olivercode" / "repo-profiles.json").unlink()
        self.assertEqual(repo_profiles.registry_file(local_config.OC_ROOT),
                         local_config.OC_ROOT / "shared" / "repo-profiles.json")

    def test_named_private_repos_with_no_registry_are_reported(self):
        (self.private / "olivercode" / "repo-profiles.json").unlink()
        gap = repo_profiles.registry_gap(local_config.OC_ROOT)
        self.assertIn("notes", gap)
        self.assertIn("privateRepos", gap)

    def test_a_found_registry_reports_no_gap(self):
        self.assertEqual(repo_profiles.registry_gap(local_config.OC_ROOT), "")

    def test_the_tracked_registry_ships_empty(self):
        tracked = json.loads((local_config.OC_ROOT / "shared" / "repo-profiles.json").read_text())
        self.assertEqual(tracked["profiles"], {})


class TestSaveLocalGuard(unittest.TestCase):
    def test_no_file_in_use_refuses_the_write(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": os.devnull}):
            with self.assertRaisesRegex(RuntimeError, "no local config file"):
                local_config.save_local({"x": 1})

    def test_a_named_scratch_file_is_written(self):
        scratch = temp_dir(self) / "local.json"
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(scratch)}):
            local_config.save_local({"x": 1})
        self.assertEqual({"x": 1}, json.loads(scratch.read_text()))


class SymlinkedExample(unittest.TestCase):
    """A configured registry that is a symlink to the tracked example counts as unset (#845)."""

    def setUp(self):
        home = temp_dir(self)
        self.link = home / "repo-profiles.json"
        self.link.symlink_to(local_config.OC_ROOT / "shared" / "repo-profiles.json")
        self.private = home / "private"
        (self.private / "olivercode").mkdir(parents=True)
        self.real = self.private / "olivercode" / "repo-profiles.json"
        self.real.write_text(json.dumps({"profiles": {"real": {}}}))
        for patcher in (mock.patch.dict("os.environ", {"OLIVERCODE_FLEET_REGISTRY": str(self.link)}),
                        mock.patch.object(repo_profiles, "private_repos", lambda: {"notes": self.private})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_private_fallback_runs(self):
        self.assertEqual(repo_profiles.registry_file(local_config.OC_ROOT), self.real)

    def test_a_missing_private_registry_is_reported_as_a_gap(self):
        self.real.unlink()
        self.assertIn("privateRepos", repo_profiles.registry_gap(local_config.OC_ROOT))

    def test_a_write_never_lands_in_the_tracked_example(self):
        self.real.unlink()
        self.assertEqual(repo_profiles.registry_write_file(local_config.OC_ROOT),
                         local_config.OC_ROOT / "shared" / "repo-profiles.local.json")


class ConfiguredRegistryPath(unittest.TestCase):
    def test_the_default_sits_under_the_olivercode_home(self):
        self.assertEqual(local_config.fleet_registry_path(), Path.home() / ".olivercode" / "fleet" / "repo-profiles.json")

    def test_the_config_key_names_the_path_and_the_registry_is_read_from_it(self):
        home = temp_dir(self)
        registry = home / "mine.json"
        registry.write_text(json.dumps({"profiles": {"x": {}}}))
        cfg = home / "local.json"
        cfg.write_text(json.dumps({"fleetRegistry": str(registry)}))
        with mock.patch.dict("os.environ", {"OLIVERCODE_LOCAL_CONFIG": str(cfg)}):
            self.assertEqual(local_config.fleet_registry_path(), registry)
            self.assertEqual(repo_profiles.load_repo_profiles(local_config.OC_ROOT), ({"x": {}}, registry))

    def test_no_fleet_names_init_fleet(self):
        self.assertIn("olivercode init-fleet", repo_profiles.NO_FLEET)

