"""Deterministic builder lifecycle event parsing and time-weighted concurrency."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import builder_telemetry


class TestBuilderTelemetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "builder-events.jsonl"
        self.base = datetime(2026, 11, 25, tzinfo=timezone.utc)

    def write(self, rows):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def row(self, event, second, worker="", claim="", **extra):
        at = self.base.replace(second=second).isoformat()
        return {"event": event, "at": at, "repo": "o/r", "worker_id": worker, "claim_id": claim, **extra}

    def test_time_weighted_average_and_peak_use_complete_worker_intervals(self):
        self.write([
            self.row("builder_started", 0, "w1"),
            self.row("builder_started", 10, "w2"),
            self.row("builder_finished", 20, "w1", outcome="landed"),
            self.row("builder_finished", 30, "w2", outcome="held"),
        ])
        now = self.base.replace(minute=2, second=59).timestamp()
        result = builder_telemetry.summarize(hours=1, now=now, path=self.path)
        self.assertAlmostEqual(40 / 3600, result["average_active"])
        self.assertEqual(2, result["peak_active"])
        self.assertEqual(1, result["completed"])
        self.assertEqual(1, result["not_landed"])

    def test_queue_wait_is_correlated_by_claim_id(self):
        self.write([
            self.row("story_claimed", 0, claim="c1"),
            self.row("builder_started", 7, "w1", "c1"),
            self.row("builder_finished", 9, "w1", "c1", outcome="landed"),
        ])
        now = self.base.replace(minute=2, second=59).timestamp()
        result = builder_telemetry.summarize(hours=1, now=now, path=self.path)
        self.assertEqual(7, result["average_queue_wait_s"])

    def test_unmatched_starts_and_ends_are_reported_not_counted_as_active(self):
        self.write([
            self.row("builder_started", 0, "w1"),
            self.row("builder_finished", 10, "unknown", outcome="landed"),
        ])
        now = self.base.replace(minute=2, second=59).timestamp()
        result = builder_telemetry.summarize(hours=1, now=now, path=self.path)
        self.assertEqual(1, result["unmatched_starts"])
        self.assertEqual(1, result["unmatched_ends"])
        self.assertIsNone(result["average_active"])

    def test_malformed_lines_are_counted_and_missing_log_is_empty(self):
        self.path.write_text("{bad json}\n", encoding="utf-8")
        rows, malformed = builder_telemetry.read(self.path)
        self.assertEqual([], rows)
        self.assertEqual(1, malformed)
        self.path.unlink()
        self.assertEqual(([], 0), builder_telemetry.read(self.path))


if __name__ == "__main__":
    unittest.main()
