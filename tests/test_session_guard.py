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

    def test_two_different_stories_can_use_two_configured_account_slots(self):
        self.cap.stop()
        cap_two = mock.patch.object(session_guard.local_config, "max_builders", return_value=2)
        cap_two.start()
        self.addCleanup(cap_two.stop)
        first = session_guard.acquire("story-20", "sonnet", "/work/Repo-20", "sid-a", repo_slug="o/r")
        entered = threading.Event()
        second = []
        def second_call():
            lease = session_guard.acquire("story-21", "sonnet", "/work/Repo-21", "sid-b", repo_slug="o/r")
            second.append(lease)
            entered.set()
        thread = threading.Thread(target=second_call)
        thread.start()
        thread.join(timeout=2)
        self.assertTrue(entered.is_set(), "a second story should use the second configured slot")
        first.finish({"cost_usd": 0.1, "stop_reason": "completed"})
        first.release()
        second[0].finish({"cost_usd": 0.1, "stop_reason": "completed"})
        second[0].release()
        rows = [json.loads(line) for line in (self.home / session_guard.LOG).read_text().splitlines()]
        starts = [r for r in rows if r["event"] == "session_start"]
        self.assertEqual(2, len(starts))
        self.assertTrue(all(r["cap"] == 2 for r in starts))

    def test_same_story_sessions_serialize_even_when_account_cap_is_two(self):
        self.cap.stop()
        cap_two = mock.patch.object(session_guard.local_config, "max_builders", return_value=2)
        cap_two.start()
        self.addCleanup(cap_two.stop)
        first = session_guard.acquire("story-12", "sonnet", "/work/Repo-12", "sid-a", repo_slug="owner/repo")
        entered = threading.Event()
        def second_call():
            lease = session_guard.acquire("story-12-fix", "sonnet", "/work/Repo-12", "sid-b", repo_slug="owner/repo")
            entered.set()
            lease.finish({"cost_usd": 0.1, "stop_reason": "completed"})
            lease.release()
        thread = threading.Thread(target=second_call)
        thread.start()
        time.sleep(0.08)
        self.assertFalse(entered.is_set(), "same-story lock should serialize even with spare account slots")
        first.finish({"cost_usd": 0.1, "stop_reason": "completed"})
        first.release()
        thread.join(timeout=2)
        self.assertTrue(entered.is_set())

    def test_unknown_or_unfinished_story_session_cost_fails_closed(self):
        lease = session_guard.acquire("story-9", "sonnet", "/work/Repo-9", "sid-9")
        self.assertTrue(session_guard.story_has_unknown_cost(9, "Repo"))
        lease.finish({"stop_reason": "completed", "exit_code": 0, "cost_usd": 0.2})
        lease.release()
        self.assertFalse(session_guard.story_has_unknown_cost(9, "Repo"))

    def test_resumed_invocations_keep_cost_and_attempts_separate(self):
        first = session_guard.acquire("story-10", "sonnet", "/work/Repo-10", "sid-10")
        first.finish({"cost_usd": 0.1, "stop_reason": "timeout"})
        first.release()
        second = session_guard.acquire("story-10", "sonnet", "/work/Repo-10", "sid-10", resumed=True)
        second.finish({"cost_usd": 0.2, "stop_reason": "completed", "resumed": True})
        second.release()
        rows = [json.loads(line) for line in (self.home / session_guard.LOG).read_text().splitlines()]
        starts = [r for r in rows if r["event"] == "session_start"]
        ends = [r for r in rows if r["event"] == "session_end"]
        self.assertEqual([1, 2], [r["attempt"] for r in starts])
        self.assertEqual([0.1, 0.2], [r["cost_usd"] for r in ends])
        self.assertFalse(session_guard.story_has_unknown_cost(10, "Repo"))

    def test_story_spend_ceiling_blocks_internal_fix_or_review_sessions(self):
        (self.home / session_guard.LOG).write_text(
            '{"event":"session_end","session":"story-7","session_id":"sid-7","repo":"o/r","cost_usd":6.0}\n',
            encoding="utf-8")
        with mock.patch.object(session_guard.local_config, "max_story_spend", return_value=6.0):
            with self.assertRaisesRegex(RuntimeError, "reaching its"):
                session_guard.acquire("story-7-fix", "sonnet", "/work/Repo-7", "sid-7-fix", repo_slug="o/r")
        rows = [json.loads(line) for line in (self.home / session_guard.LOG).read_text().splitlines()]
        self.assertEqual(1, len(rows), "no session-start event is written when the story is already at its ceiling")

    def test_attempt_ceiling_persists_and_blocks_new_session(self):
        rows = []
        for n in range(8):
            rows.append({"event": "session_start", "session": "story-8", "session_id": f"sid-{n}", "repo": "o/r"})
            rows.append({"event": "session_end", "session": "story-8", "session_id": f"sid-{n}", "repo": "o/r", "cost_usd": 0.1})
        (self.home / session_guard.LOG).write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        with mock.patch.object(session_guard.local_config, "max_story_attempts", return_value=8):
            with self.assertRaisesRegex(RuntimeError, "attempt ceiling"):
                session_guard.acquire("story-8-fix", "sonnet", "/work/Repo-8", "sid-next", repo_slug="o/r")
        saved = [json.loads(line) for line in (self.home / session_guard.LOG).read_text().splitlines()]
        self.assertEqual(16, len(saved), "exhaustion does not append another start record")

    def test_start_telemetry_failure_refuses_to_launch_and_releases_slot(self):
        with mock.patch.object(session_guard, "_write", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "durable session-start telemetry"):
                session_guard.acquire("story-1", "sonnet", "/work/Repo-1", "sid-x")
        lease = session_guard.acquire("story-1", "sonnet", "/work/Repo-1", "sid-y")
        lease.finish({"cost_usd": 0.01, "stop_reason": "completed"})
        lease.release()


if __name__ == "__main__":
    unittest.main()
