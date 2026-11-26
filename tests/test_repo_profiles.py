"""Tests for scripts/lib/repo_profiles.py: reading the fleet registry and finding each repo.

Where the registry file is read from is covered in tests/test_registry_location.py. This
file covers what the loader returns, where each fleet repo resolves to, and which repos
count as the fleet.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import load_script

repo_profiles = load_script("scripts/lib/repo_profiles.py", "repo_profiles")


class RepoProfilesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # This machine's olivercode.local.json must not leak into the results.
        self.local_paths = {}
        patcher = mock.patch.object(repo_profiles, "repo_paths", lambda: self.local_paths)
        patcher.start()
        self.addCleanup(patcher.stop)

    def registry(self, text):
        (self.root / "shared").mkdir(exist_ok=True)
        path = self.root / "shared" / "repo-profiles.json"
        path.write_text(text)
        return path


class LoadRepoProfiles(RepoProfilesBase):
    def test_returns_the_profiles_and_the_file_they_came_from(self):
        path = self.registry(json.dumps({"profiles": {"alpha": {"tier": 1}}, "unmanagedRepoWaivers": []}))
        self.assertEqual(({"alpha": {"tier": 1}}, path), repo_profiles.load_repo_profiles(self.root))

    def test_a_registry_without_profiles_is_an_empty_fleet(self):
        self.registry(json.dumps({"unmanagedRepoWaivers": []}))
        self.assertEqual({}, repo_profiles.load_repo_profiles(self.root)[0])

    def test_a_missing_registry_raises(self):
        with self.assertRaises(FileNotFoundError):
            repo_profiles.load_repo_profiles(self.root)

    def test_a_malformed_registry_raises(self):
        self.registry("{not json")
        with self.assertRaises(json.JSONDecodeError):
            repo_profiles.load_repo_profiles(self.root)


class ResolveRepoPath(RepoProfilesBase):
    def test_a_profile_path_resolves_by_its_form(self):
        # No path is the sibling folder; a relative path sits under the fleet root, an absolute one is
        # used as written and a home-relative one expands.
        for profile, expected in (({}, Path("/fleet/alpha")),
                                  ({"path": "clients/alpha"}, Path("/fleet/clients/alpha")),
                                  ({"path": "/elsewhere/alpha"}, Path("/elsewhere/alpha")),
                                  ({"path": "~/code/alpha"}, Path.home() / "code" / "alpha")):
            with self.subTest(profile=profile):
                self.assertEqual(expected, repo_profiles.resolve_repo_path("alpha", profile, Path("/fleet")))

    def test_this_machines_path_wins_over_the_profile(self):
        self.local_paths = {"alpha": Path("/this/machine/alpha")}
        self.assertEqual(
            Path("/this/machine/alpha"),
            repo_profiles.resolve_repo_path("alpha", {"path": "/elsewhere/alpha"}, Path("/fleet")),
        )


class IterFleet(RepoProfilesBase):
    def test_the_framework_repo_is_skipped_in_any_casing(self):
        profiles = {"OliverCode": {}, "olivercode": {}, "alpha": {}, "beta": {"path": "/b"}}
        self.assertEqual(
            [("alpha", {}, Path("/fleet/alpha")), ("beta", {"path": "/b"}, Path("/b"))],
            list(repo_profiles.iter_fleet(profiles, Path("/fleet"))),
        )

    def test_an_empty_registry_yields_nothing(self):
        self.assertEqual([], list(repo_profiles.iter_fleet({}, Path("/fleet"))))
