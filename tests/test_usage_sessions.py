import json
import os
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import usage_sessions  # noqa: E402

NOW = 1_800_000_000.0


class TestPeriodUsage(unittest.TestCase):
    def test_transcript_start_uses_first_assistant_call_and_deduplicates_stream_rows(self):
        path = temp_dir(self) / "chat.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in [
            {"type": "user", "timestamp": "2026-11-25T10:00:00Z", "message": {"content": "hello"}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "first", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90}}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "first", "usage": {"input_tokens": 20, "cache_read_input_tokens": 100}}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:02Z", "message": {"id": "second", "usage": {"input_tokens": 500}}},
        ]), encoding="utf-8")
        self.assertEqual((1795600801, 120), usage_sessions.transcript_start(path))

    def test_headless_builder_transcripts_are_excluded(self):
        path = temp_dir(self) / "builder.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in [
            {"type": "user", "entrypoint": "sdk-cli", "timestamp": "2026-11-25T10:00:00Z", "message": {"content": "build"}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "m", "usage": {"input_tokens": 12}}},
        ]), encoding="utf-8")
        self.assertIsNone(usage_sessions.transcript_start(path))

    def test_recent_chat_starts_filters_by_first_call_timestamp(self):
        root = temp_dir(self) / "projects"
        project = root / "work"
        project.mkdir(parents=True)
        path = project / "recent.jsonl"
        path.write_text(json.dumps({"type": "assistant", "timestamp": "2026-11-25T10:00:00Z", "message": {"id": "m", "usage": {"input_tokens": 12}}}) + "\n", encoding="utf-8")
        self.assertEqual([(path, 12)], usage_sessions.recent_chat_starts(root, days=7, now=1795600800))

    def test_a_message_logged_twice_keeps_the_largest_of_each_count_not_the_largest_row(self):
        path, day = temp_dir(self) / "t.jsonl", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW))
        rows = [{"input_tokens": 9, "output_tokens": 1}, {"input_tokens": 2, "output_tokens": 50}]
        path.write_text("".join(json.dumps({"timestamp": day, "message": {"id": "m", "usage": u}}) + "\n" for u in rows), encoding="utf-8")
        self.assertEqual((9, 50, 0), usage_sessions.period_usage(path, NOW - 60))


if __name__ == "__main__":
    unittest.main()


def iso(stamp):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


def day(stamp):
    return time.strftime("%Y-%m-%d", time.localtime(stamp))


def call(stamp, message_id, tokens, entrypoint=None):
    row = {"type": "assistant", "timestamp": iso(stamp), "message": {"id": message_id, "usage": {"input_tokens": tokens // 2, "cache_read_input_tokens": tokens - tokens // 2}}}
    return {**row, "entrypoint": entrypoint} if entrypoint else row


class TestChatSpend(unittest.TestCase):
    """The per-day desktop chat tokens behind the spend panel (#1150)."""

    def projects(self, files, modified=NOW):
        root = temp_dir(self) / "projects"
        (root / "work").mkdir(parents=True)
        for name, rows in files.items():
            path = root / "work" / f"{name}.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            os.utime(path, (modified, modified))
        return root

    def test_each_day_sums_the_tokens_read_the_calls_and_the_start_size_of_desktop_chats_only(self):
        root = self.projects({
            "chat-a": [call(NOW, "m1", 100), call(NOW, "m1", 120), call(NOW + 5, "m2", 300), call(NOW - 86400, "m0", 50)],
            "chat-b": [call(NOW + 9, "m3", 40)],
            "builder": [call(NOW, "b1", 9999, entrypoint="sdk-cli")],
        })
        out = usage_sessions.chat_spend(root, days=7, now=NOW + 60, cache_path=temp_dir(self) / "cache.json")
        today = out[day(NOW)]
        self.assertEqual((120 + 300 + 40, 3), (today["tokens"], today["calls"]), "a message id counts once at its largest, and a headless session is the runner's")
        self.assertEqual([("chat-a", 420, 2), ("chat-b", 40, 1)], sorted(today["chats"], key=lambda c: -c[1]))
        self.assertEqual([40], [s for s in today["starts"] if s == 40], "each chat's first call is its start size")
        self.assertEqual(50, out[day(NOW - 86400)]["tokens"])

    def test_a_day_outside_the_window_and_a_stale_file_are_left_out(self):
        root = self.projects({"old": [call(NOW - 10 * 86400, "m", 70)]}, modified=NOW - 10 * 86400)
        self.assertEqual({}, usage_sessions.chat_spend(root, days=7, now=NOW, cache_path=temp_dir(self) / "cache.json"))

    def test_a_transcript_that_did_not_change_is_read_once(self):
        root = self.projects({"chat": [call(NOW, "m", 100)]})
        cache = temp_dir(self) / "cache.json"
        usage_sessions.chat_spend(root, days=7, now=NOW + 1, cache_path=cache)
        with mock.patch.object(usage_sessions, "_scan_chat", side_effect=AssertionError("read again")):
            again = usage_sessions.chat_spend(root, days=7, now=NOW + 1, cache_path=cache)
        self.assertEqual(100, again[day(NOW)]["tokens"])

