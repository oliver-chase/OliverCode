"""Tests for the scheduler tick: a hung job is logged and the next job still runs, and a failed job stays due."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import load_script

tick = load_script("scripts/local-scheduler/tick.py", "scheduler_tick")


class TickCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-tick-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.object(tick, "LOG_DIR", self.tmp / "logs")
        patcher.start()
        self.addCleanup(patcher.stop)
        tick.ensure_dirs()

    def log_text(self):
        return (self.tmp / "logs" / "scheduler.log").read_text()


class TestRunJob(TickCase):
    def test_a_timeout_is_logged_and_leaves_the_job_due(self):
        marker = self.tmp / "marker"
        with mock.patch.object(tick.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            tick.run_job("hung", marker, ["audit-fleet"])
        self.assertIn("hung: TIMED OUT", self.log_text())
        self.assertFalse(marker.exists())

    def test_a_job_after_a_timeout_still_runs(self):
        first, second = self.tmp / "first", self.tmp / "second"
        ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        jobs = [("hung", first, 0, ["a"]), ("fine", second, 0, ["b"])]
        with mock.patch.object(tick, "JOBS", jobs), \
                mock.patch.object(tick.subprocess, "run", side_effect=[subprocess.TimeoutExpired("x", 1), ok]):
            self.assertEqual(tick.main(), 0)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())

    def test_a_failed_job_keeps_its_marker_untouched(self):
        marker = self.tmp / "marker"
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(tick.subprocess, "run", return_value=failed):
            tick.run_job("bad", marker, ["push-fleet"])
        self.assertFalse(marker.exists())
        self.assertIn("bad: FAILED", self.log_text())


if __name__ == "__main__":
    unittest.main()


class TestSharedCadence(unittest.TestCase):
    def test_tick_and_the_health_check_read_the_same_constants(self):
        from lib import health_checks, scheduler_constants as c
        self.assertEqual(c.PUSH_FLEET_INTERVAL_S, tick.PUSH_FLEET_INTERVAL_S)
        self.assertEqual(c.AUDIT_FLEET_INTERVAL_S, tick.AUDIT_FLEET_INTERVAL_S)
        self.assertEqual({"push-fleet": c.PUSH_FLEET_CADENCE_S, "audit-fleet": c.AUDIT_FLEET_CADENCE_S},
                         {name: interval for name, _, interval in health_checks.SCHEDULER_JOBS})
        self.assertLess(c.PUSH_FLEET_INTERVAL_S, c.PUSH_FLEET_CADENCE_S)
        self.assertLess(c.AUDIT_FLEET_INTERVAL_S, c.AUDIT_FLEET_CADENCE_S)
