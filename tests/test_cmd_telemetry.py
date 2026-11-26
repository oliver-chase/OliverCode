"""Owner-facing builder telemetry command argument and output behavior."""

import contextlib
import io
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import builder_telemetry, cmd_telemetry


class TestTelemetryCommand(unittest.TestCase):
    def setUp(self):
        self.data = {
            "builder_starts": 2, "completed": 1, "not_landed": 1,
            "coverage_seconds": 1800, "average_active": 0.5, "peak_active": 1,
            "average_queue_wait_s": 12.0, "unmatched_starts": 0,
            "unmatched_ends": 0, "malformed_events": 0,
        }

    def test_default_window_prints_summary(self):
        output = io.StringIO()
        with mock.patch.object(builder_telemetry, "summarize", return_value=self.data) as summarize:
            with contextlib.redirect_stdout(output):
                code = cmd_telemetry.command_telemetry([])
        self.assertEqual(0, code)
        summarize.assert_called_once_with(24.0)
        self.assertIn("Builder starts: 2", output.getvalue())
        self.assertIn("Average active builders: 0.50", output.getvalue())

    def test_custom_window_is_passed_to_summary(self):
        with mock.patch.object(builder_telemetry, "summarize", return_value=self.data) as summarize:
            with contextlib.redirect_stdout(io.StringIO()):
                code = cmd_telemetry.command_telemetry(["--hours", "72"])
        self.assertEqual(0, code)
        summarize.assert_called_once_with(72.0)

    def test_invalid_window_and_unknown_arguments_return_usage(self):
        for args in (["--hours", "0"], ["--hours", "8761"], ["--wat"]):
            with self.subTest(args=args), mock.patch.object(builder_telemetry, "summarize") as summarize:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = cmd_telemetry.command_telemetry(args)
                self.assertEqual(2, code)
                summarize.assert_not_called()
                self.assertIn("Usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
