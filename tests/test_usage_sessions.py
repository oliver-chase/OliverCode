import json
import sys
import time
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import usage_sessions  # noqa: E402

NOW = 1_800_000_000.0


class TestPeriodUsage(unittest.TestCase):
    def test_transcript_start_uses_first_assistant_call_and_deduplicates_stream_rows(self):
        path = temp_dir(self) / "chat.jsonl"
        path.write_text("".join(json.dumps(row) + "\\n" for row in [
            {"type": "user", "timestamp": "2026-11-25T10:00:00Z", "message": {"content": "hello"}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "first", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90}}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "first", "usage": {"input_tokens": 20, "cache_read_input_tokens": 100}}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:02Z", "message": {"id": "second", "usage": {"input_tokens": 500}}},
        ]), encoding="utf-8")
        self.assertEqual((1795600801, 120), usage_sessions.transcript_start(path))

    def test_headless_builder_transcripts_are_excluded(self):
        path = temp_dir(self) / "builder.jsonl"
        path.write_text("".join(json.dumps(row) + "\\n" for row in [
            {"type": "user", "entrypoint": "sdk-cli", "timestamp": "2026-11-25T10:00:00Z", "message": {"content": "build"}},
            {"type": "assistant", "timestamp": "2026-11-25T10:00:01Z", "message": {"id": "m", "usage": {"input_tokens": 12}}},
        ]), encoding="utf-8")
        self.assertIsNone(usage_sessions.transcript_start(path))

    def test_recent_chat_starts_filters_by_first_call_timestamp(self):
        root = temp_dir(self) / "projects"
        project = root / "work"
        project.mkdir(parents=True)
        path = project / "recent.jsonl"
        path.write_text(json.dumps({"type": "assistant", "timestamp": "2026-11-25T10:00:00Z", "message": {"id": "m", "usage": {"input_tokens": 12}}}) + "\\n", encoding="utf-8")
        self.assertEqual([(path, 12)], usage_sessions.recent_chat_starts(root, days=7, now=1795600800))

    def test_a_message_logged_twice_keeps_the_largest_of_each_count_not_the_largest_row(self):
        path, day = temp_dir(self) / "t.jsonl", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW))
        rows = [{"input_tokens": 9, "output_tokens": 1}, {"input_tokens": 2, "output_tokens": 50}]
        path.write_text("".join(json.dumps({"timestamp": day, "message": {"id": "m", "usage": u}}) + "\n" for u in rows), encoding="utf-8")
        self.assertEqual((9, 50, 0), usage_sessions.period_usage(path, NOW - 60))


if __name__ == "__main__":
    unittest.main()
