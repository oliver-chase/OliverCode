"""The fleet registry is read from a private repo when this checkout names one.

The tracked shared/ registry ships as an empty example so a fork carries no operator data.
A checkout that names a private repo holding olivercode/repo-profiles.json must read that
copy, or every fleet command would silently see an empty fleet.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import local_config, repo_profiles  # noqa: E402


class RegistryLocation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.private = Path(self.tmp.name) / "private"
        (self.private / "olivercode").mkdir(parents=True)
        (self.private / "olivercode" / "repo-profiles.json").write_text(json.dumps({"profiles": {"real": {}}}))
        p = mock.patch.object(repo_profiles, "private_repos", lambda: {"notes": self.private})
        p.start()
        self.addCleanup(p.stop)

    def test_this_checkout_reads_the_private_repos_copy(self):
        profiles, path = repo_profiles.load_repo_profiles(local_config.OC_ROOT)
        self.assertEqual((list(profiles), path), (["real"], self.private / "olivercode" / "repo-profiles.json"))

    def test_another_root_reads_its_own_shared_copy(self):
        other = Path(self.tmp.name) / "fork"
        (other / "shared").mkdir(parents=True)
        (other / "shared" / "repo-profiles.json").write_text(json.dumps({"profiles": {}}))
        self.assertEqual(repo_profiles.registry_file(other, "repo-profiles.json"), other / "shared" / "repo-profiles.json")

    def test_a_private_repo_without_a_registry_falls_back_to_the_tracked_example(self):
        (self.private / "olivercode" / "repo-profiles.json").unlink()
        self.assertEqual(repo_profiles.registry_file(local_config.OC_ROOT, "repo-profiles.json"),
                         local_config.OC_ROOT / "shared" / "repo-profiles.json")

    def test_the_tracked_registry_ships_empty(self):
        tracked = json.loads((local_config.OC_ROOT / "shared" / "repo-profiles.json").read_text())
        self.assertEqual((tracked["profiles"], tracked["unmanagedRepoWaivers"]), ({}, []))


if __name__ == "__main__":
    unittest.main()
