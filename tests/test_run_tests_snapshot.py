"""scripts/run-tests.sh runs the suite from a clean clone of HEAD and names the commit."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo

RUNNER = REPO_ROOT / "scripts" / "run-tests.sh"
PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
FAILING = PASSING.replace("pass", "self.fail('boom')")


class RunTestsSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = scratch_repo(Path(self.tmp.name) / "repo")
        (self.repo / "tests").mkdir()
        self.test_file = self.repo / "tests" / "test_x.py"
        self.test_file.write_text(PASSING)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "base")
        self.sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def run_runner(self):
        return subprocess.run(["bash", str(RUNNER), str(self.repo)], env=git_env(),
                              capture_output=True, text=True)

    def test_uncommitted_edits_and_untracked_tests_are_not_read(self):
        self.test_file.write_text(FAILING)
        (self.repo / "tests" / "test_new.py").write_text(FAILING)
        result = self.run_runner()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_report_names_the_commit_on_pass_and_on_failure(self):
        self.assertIn(self.sha, self.run_runner().stdout)
        self.test_file.write_text(FAILING)
        git(self.repo, "commit", "-q", "-am", "break")
        sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(sha, result.stdout)


if __name__ == "__main__":
    unittest.main()
