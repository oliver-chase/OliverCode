"""The structure checker that bootstrap copies into a repo must pass a repo shaped the way bootstrap leaves it.

It once required a retired story registry under .github, so every freshly bootstrapped repo failed it.
"""
import shutil
import subprocess
import unittest

from _support import REPO_ROOT, scratch_repo, temp_dir

CHECKER = REPO_ROOT / "core" / "templates" / "project" / "scripts" / "check-structure-contract.mjs"


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node and git")
class TestStructureContract(unittest.TestCase):
    def setUp(self):
        self.repo = scratch_repo(temp_dir(self, "structure-contract-"))
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        (self.repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")

    def run_checker(self):
        return subprocess.run(["node", str(CHECKER)], cwd=self.repo, capture_output=True, text=True)

    def test_a_repo_without_the_retired_story_registry_passes(self):
        result = self.run_checker()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_legacy_backlog_file_or_a_missing_package_script_fails(self):
        (self.repo / ".github" / "backlog.md").write_text("# old\n")
        (self.repo / "package.json").write_text('{"scripts": {"a": "bash scripts/missing.sh", "b": "python3 scripts/gone.py"}}')
        result = self.run_checker()
        self.assertEqual(1, result.returncode)
        for name in ("legacy backlog.md", "scripts/missing.sh", "scripts/gone.py"):
            self.assertIn(name, result.stderr)
