"""Health must say when the local scheduler is missing or a job has gone stale."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.health_checks import SCHEDULER_LABEL, _check_scheduler  # noqa: E402


class TestSchedulerHealth(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="scheduler-health-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.agents = self.home / "Library" / "LaunchAgents"
        self.state = self.home / "Library" / "Application Support" / "olivercode-scheduler"

    def install(self):
        self.agents.mkdir(parents=True)
        (self.agents / f"{SCHEDULER_LABEL}.plist").write_text("x")
        self.state.mkdir(parents=True)

    def test_no_launchd_is_not_checked(self):
        self.assertEqual((0, 0, 0), _check_scheduler(self.home))

    def test_missing_scheduler_warns(self):
        self.agents.mkdir(parents=True)
        self.assertEqual((0, 0, 1), _check_scheduler(self.home))

    def test_fresh_jobs_pass_and_a_stale_one_warns(self):
        self.install()
        (self.state / "last-push-fleet").write_text("")
        stale = self.state / "last-audit-fleet"
        stale.write_text("")
        old = time.time() - 30 * 86400
        os.utime(stale, (old, old))
        self.assertEqual((1, 0, 1), _check_scheduler(self.home))


if __name__ == "__main__":
    unittest.main()
