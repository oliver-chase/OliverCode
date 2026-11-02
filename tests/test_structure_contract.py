"""The structure checker that bootstrap copies into a repo must pass a repo shaped the way bootstrap leaves it.

It once required a retired story registry under .github, so every freshly bootstrapped repo failed it.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, scratch_repo

CHECKER = REPO_ROOT / "core" / "templates" / "project" / "scripts" / "check-structure-contract.mjs"


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node and git")
class TestStructureContract(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="structure-contract-"))
        scratch_repo(self.repo)
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        (self.repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def run_checker(self):
        return subprocess.run(["node", str(CHECKER)], cwd=self.repo, capture_output=True, text=True)

    def test_a_repo_without_the_retired_story_registry_passes(self):
        result = self.run_checker()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_legacy_backlog_file_still_fails(self):
        (self.repo / ".github" / "backlog.md").write_text("# old\n")
        result = self.run_checker()
        self.assertEqual(1, result.returncode)
        self.assertIn("legacy backlog.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
