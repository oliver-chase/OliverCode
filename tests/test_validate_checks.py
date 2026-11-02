"""`validate.sh --check-repo`: the bloat and code quality checks, run on a scratch repo."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo

VALIDATE = REPO_ROOT / "scripts" / "validate.sh"


class CheckRepo(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-checkrepo-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        scratch_repo(self.repo)

    def add(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(self.repo, "add", rel)

    def run_check(self):
        return subprocess.run(["bash", str(VALIDATE), "--check-repo", str(self.repo)],
                              capture_output=True, text=True, env=git_env())

    def test_a_clean_repo_passes(self):
        self.add("README.md", "# Fine\n")
        self.add("tool.py", "print('ok')\n")
        self.assertEqual(0, self.run_check().returncode)

    def test_a_tracked_archive_directory_fails(self):
        self.add("archive/old.md", "# Old\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode)
        self.assertIn("archive/old.md", result.stdout)

    def test_a_file_that_marks_itself_historical_fails(self):
        self.add("notes.md", "Status: SUPERSEDED\n\nOld text.\n")
        self.assertIn("notes.md", self.run_check().stdout)

    def test_a_tracked_symlink_to_a_directory_passes(self):
        self.add("README.md", "# Fine\n")
        (self.repo / "real").mkdir()
        (self.repo / "link").symlink_to("real", target_is_directory=True)
        git(self.repo, "add", "link")
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("syntax error", result.stderr)

    def test_a_python_syntax_error_fails(self):
        self.add("broken.py", "def (:\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode)
        self.assertIn("syntax error in", result.stdout)

    def test_a_lib_module_no_test_mentions_fails(self):
        self.add("scripts/lib/orphan.py", "X = 1\n")
        self.add("tests/test_other.py", "import unittest\n")
        self.assertIn("scripts/lib/orphan.py", self.run_check().stdout)

    def test_a_lib_module_a_test_mentions_passes(self):
        self.add("scripts/lib/covered.py", "X = 1\n")
        self.add("tests/test_covered.py", "import covered\n")
        self.assertEqual(0, self.run_check().returncode)


if __name__ == "__main__":
    unittest.main()
