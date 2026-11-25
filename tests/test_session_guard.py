"""Shared Claude CLI concurrency and telemetry tests."""
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import session_guard  # noqa: E402


class TestSessionGuard(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cap = mock.patch.object(session_guard.local_config, "max_builders", return_value=1)
        self.cap.start()
        self.addCleanup(self.cap.stop)

    def test_one_slot_serializes_model_sessions_across_threads_and_logs_metadata(self):
        first = session_guard.acquire("story-4", "sonnet", "/work/Repo-4", "sid-1")
        got_second = threading.Event()
        def second_call():
            lease = session_guard.acquire("story-4-fix", "sonnet", "/work/Repo-4", "sid-2")
            got_second.set()
            lease.finish({"stop_reason": "completed", "exit_code": 0, "cost_usd": 0.25,
                          "usage": {"input": 1, "output": 2}, "tokens": 3})
            lease.release()
        thread = threading.Thread(target=second_call)
        thread.start()
        time.sleep(0.08)
        self.assertFalse(got_second.is_set(), "second model call must wait while the only slot is held")
        first.finish({"stop_reason": "completed", "exit_code": 0, "cost_usd": 0.1,
                      "usage": {"input": 2, "output": 3}, "tokens": 5})
        first.release()
        thread.join(timeout=2)
        self.assertTrue(got_second.is_set())
        rows = [json.loads(line) for line in (self.home / session_guard.LOG).read_text().splitlines()]
        starts = [r for r in rows if r["event"] == "session_start"]
        ends = [r for r in rows if r["event"] == "session_end"]
        self.assertEqual(2, len(starts))
        self.assertEqual(2, len(ends))
        self.assertTrue(all(r["cap"] == 1 and r["active_sessions"] == 1 for r in starts))
        self.assertEqual({"sid-1", "sid-2"}, {r["session_id"] for r in ends})
        self.assertTrue(all(r["cost_usd"] is not None for r in ends))

    def test_unknown_or_unfinished_story_session_cost_fails_closed(self):
        lease = session_guard.acquire("story-9", "sonnet", "/work/Repo-9", "sid-9")
        self.assertTrue(session_guard.story_has_unknown_cost(9, "Repo"))
        lease.finish({"stop_reason": "completed", "exit_code": 0, "cost_usd": 0.2})
        lease.release()
        self.assertFalse(session_guard.story_has_unknown_cost(9, "Repo"))

    def test_start_telemetry_failure_refuses_to_launch_and_releases_slot(self):
        with mock.patch.object(session_guard, "_write", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "durable session-start telemetry"):
                session_guard.acquire("story-1", "sonnet", "/work/Repo-1", "sid-x")
        lease = session_guard.acquire("story-1", "sonnet", "/work/Repo-1", "sid-y")
        lease.finish({"cost_usd": 0.01, "stop_reason": "completed"})
        lease.release()


if __name__ == "__main__":
    unittest.main()
