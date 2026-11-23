"""#1017: a session starts with one status line and no forced read, and install points one stable path at the checkout."""

import contextlib
import io
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_install, cmd_status  # noqa: E402
from test_claude_hooks import RepoCase  # noqa: E402
from test_launcher_commands import HomeCase  # noqa: E402

session = load_script("scripts/hooks/session_check.py")
NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


class TestStatusLine(RepoCase):
    def setUp(self):
        super().setUp()
        self.digest = self.tmp / "status-digest.md"
        self.digest.write_text("# Status digest\nBoard: o/r: 7 open. In the last 7 days 2 closed and 1 opened, so 0.3 stories landed per day.\n", encoding="utf-8")
        self.stale = time.time() - 660  # eleven minutes old, past DIGEST_TTL

    def line(self, env=None, fresh=True, held=None, write=None):
        """The status line with GitHub reads and the run lock stubbed. Returns the lines and the mock for the fresh read."""
        if not fresh:
            os.utime(self.digest, (self.stale, self.stale))
        write = write or mock.Mock(return_value=(self.digest, "t", 3))
        with mock.patch.dict(os.environ, env or {}), mock.patch("lib.repo_state.origin", return_value="o/r"), \
                mock.patch("lib.cmd_status.digest_path", return_value=self.digest), mock.patch("lib.cmd_status.write_digest", write), \
                mock.patch("lib.run_lock.active", return_value=held or {}):
            return session.status_line(self.repo), write

    def test_a_governed_repo_gets_one_line_that_tells_the_session_nothing_to_read(self):
        self.gates(point_git_at_them=True)
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        lines, write = self.line(fresh=False)
        self.assertEqual(["o/r: 3 open stories, none building."], lines)
        write.assert_called_once()

    def test_a_digest_under_ten_minutes_old_is_reused_and_no_github_call_is_made(self):
        self.gates(point_git_at_them=True)
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        lines, write = self.line(write=mock.Mock(side_effect=AssertionError("GitHub was read")))
        self.assertEqual(["o/r: 7 open stories, none building."], lines)
        write.assert_not_called()

    def test_a_run_names_the_story_building_and_that_requests_join_the_queue(self):
        self.gates(point_git_at_them=True)
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        lines, _ = self.line(held={"building": [42]})
        self.assertEqual(["o/r: 7 open stories, building #42. A request joins the queue as a story."], lines)

    def test_a_headless_builder_gets_none_and_refreshes_nothing(self):
        self.gates(point_git_at_them=True)
        lines, write = self.line({"OLIVERCODE_HEADLESS": "1"}, fresh=False)
        self.assertEqual([], lines)
        write.assert_not_called()

    def test_a_repo_without_gates_gets_none(self):
        os.environ.pop("OLIVERCODE_HEADLESS", None)
        lines, write = self.line(fresh=False)
        self.assertEqual([], lines)
        write.assert_not_called()


class TestCachedOpen(unittest.TestCase):
    def test_only_a_digest_under_ten_minutes_old_for_the_same_repo_gives_its_count(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            path = Path(tmp) / "status-digest.md"
            path.write_text("Board: o/r: 14 open. x\n", encoding="utf-8")
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            self.assertEqual(14, cmd_status.cached_open("o/r", NOW + timedelta(minutes=9), path))
            self.assertIsNone(cmd_status.cached_open("o/r", NOW + timedelta(minutes=10), path))
            self.assertIsNone(cmd_status.cached_open("x/y", NOW + timedelta(minutes=1), path))
            self.assertIsNone(cmd_status.cached_open("o/r", NOW, Path(tmp) / "absent.md"))


class TestInstallLink(HomeCase):
    def test_install_points_one_stable_path_at_the_checkout_and_uninstall_removes_it(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_install.command_install(self.root)
        link = self.tmp / ".claude" / "olivercode"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.root.resolve())
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_install.command_uninstall(self.root)
        self.assertFalse(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
