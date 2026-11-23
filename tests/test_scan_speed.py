"""Fleet and health commands do less work: repo discovery prunes noise folders, and a small failure log is never re-read."""

import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_repo, failure_log, schedules  # noqa: E402


class TestScanSpeed(unittest.TestCase):
    def test_discovery_finds_repos_and_prunes_noise_and_git_folders(self):
        root = temp_dir(self)
        for rel in ("a/.git/objects", "b/c/.git/hooks", "node_modules/x/.git", "_worktrees/w/.git"):
            (root / rel).mkdir(parents=True)
        (root / "linked").mkdir()
        (root / "linked" / ".git").write_text("gitdir: elsewhere")
        found = sorted(p.relative_to(root).as_posix() for p in cmd_repo._git_entries(root))
        self.assertEqual(found, ["a/.git", "b/c/.git", "linked/.git"])

    def test_a_root_inside_a_noise_folder_yields_nothing(self):
        root = temp_dir(self) / "_worktrees" / "r"
        (root / ".git").mkdir(parents=True)
        self.assertEqual(list(cmd_repo._git_entries(root)), [])

    def test_a_small_log_is_not_read_to_trim_it(self):
        log = temp_dir(self) / "f.log"
        log.write_text("x" * 30 + "\n")
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("read")):
            failure_log.trim(log, keep=1000)

    def test_refreshes_uses_the_jobs_it_is_given_without_listing_them_again(self):
        found = [("content-flow-dashboard-refresh", "refresh the dashboard page with claude -p", [])]
        with mock.patch.object(schedules, "jobs", side_effect=AssertionError("listed again")):
            out = schedules.refreshes(Path("/none"), Path("/none"), Path("/none"), prefixes=("",), found=found)
        self.assertEqual([name for name, _ in out], ["content-flow-dashboard-refresh"])


if __name__ == "__main__":
    unittest.main()
