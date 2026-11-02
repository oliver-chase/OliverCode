"""link-check.sh and validate.sh pass paths to python3 as arguments, so a quote in the path breaks neither."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo


class QuotedCheckout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="olivercode-quote-"))
        cls.addClassCleanup(shutil.rmtree, cls.base, ignore_errors=True)
        cls.repo = scratch_repo(cls.base / "it's here")
        tracked = git(REPO_ROOT, "ls-files", "-z").stdout.split("\0")
        for rel in filter(None, tracked):
            src = REPO_ROOT / rel
            if src.is_file() or src.is_symlink():
                dest = cls.repo / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest, follow_symlinks=False)

    def run_script(self, *args):
        return subprocess.run(["bash", *args], cwd=self.repo, capture_output=True, text=True, env=git_env())

    def test_link_check_runs_in_a_path_with_a_single_quote(self):
        result = self.run_script("scripts/link-check.sh", "--quiet")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_the_consistency_check_runs_in_a_path_with_a_single_quote(self):
        result = self.run_script("scripts/validate.sh", "--check-consistency")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
