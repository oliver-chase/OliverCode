"""City refreshes itself (#1350): log_stage and board sync rewrite city.html from local files."""

import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import agent_loop, cmd_boardsweep, failure_log  # noqa: E402
from lib.local_config import OC_ROOT  # noqa: E402


class TestCityRefresh(unittest.TestCase):
    def setUp(self):
        agent_loop.CITY_AT = 0.0

    def test_a_stage_row_rewrites_the_page_at_most_once_a_minute(self):
        home = temp_dir(self)
        with mock.patch.object(failure_log, "home", return_value=home), mock.patch("lib.city.refresh") as refresh:
            agent_loop.log_stage("story-1", "r", "claimed")
            agent_loop.log_stage("story-1", "r", "building")
            self.assertEqual(refresh.call_count, 1)
            refresh.assert_called_with(OC_ROOT)
            agent_loop.CITY_AT -=agent_loop.CITY_EVERY
            agent_loop.log_stage("run-r", "r", "run-end", landed=1, stopped=0)
            self.assertEqual(refresh.call_count, 2)

    def test_a_failed_rewrite_does_not_stop_the_drain(self):
        home = temp_dir(self)
        with mock.patch.object(failure_log, "home", return_value=home), mock.patch("lib.city.refresh", side_effect=ValueError("bad")):
            agent_loop.log_stage("story-1", "r", "claimed")
            self.assertIn("claimed", (home / "run-log.jsonl").read_text())

    def test_board_sync_rewrites_the_page_but_a_dry_run_does_not(self):
        with mock.patch.object(cmd_boardsweep, "run", return_value=0), mock.patch("lib.city.refresh") as refresh:
            self.assertEqual(cmd_boardsweep.command_board_sweep([]), 0)
            self.assertEqual(refresh.call_count, 1)
            refresh.assert_called_once_with(OC_ROOT)
            cmd_boardsweep.command_board_sweep(["--dry-run"])
            self.assertEqual(refresh.call_count, 1)

    def test_a_failed_rewrite_does_not_fail_the_board_sync(self):
        with mock.patch.object(cmd_boardsweep, "run", return_value=0), mock.patch("lib.city.refresh", side_effect=ValueError("bad")):
            self.assertEqual(cmd_boardsweep.command_board_sweep([]), 0)


if __name__ == "__main__":
    unittest.main()
