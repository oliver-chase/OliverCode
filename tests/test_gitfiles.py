"""Tests for scripts/lib/gitfiles.py: one reader of `git ls-files` for the checks that list a repo's files."""
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import git, load_script, scratch_repo, temp_dir

gitfiles = load_script("scripts/lib/gitfiles.py", "gitfiles")


class TestTrackedFiles(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self, "gitfiles-")
        scratch_repo(self.repo)
        (self.repo / "a.md").write_text("a\n")
        (self.repo / "run.sh").write_text("x\n")
        git(self.repo, "add", "-A")

    def test_it_lists_the_tracked_paths_and_filters_by_pattern(self):
        self.assertEqual(sorted(gitfiles.tracked_files(self.repo)), ["a.md", "run.sh"])
        self.assertEqual(gitfiles.tracked_files(self.repo, "*.sh"), ["run.sh"])

    def test_a_folder_that_is_not_a_repo_lists_nothing(self):
        plain = Path(tempfile.mkdtemp(prefix="gitfiles-plain-"))
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        self.assertEqual(gitfiles.tracked_files(plain), [])


if __name__ == "__main__":
    unittest.main()
