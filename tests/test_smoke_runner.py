"""Live progress from the parallel smoke-test runner."""

import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import smoke_runner  # noqa: E402


class TestSmokeProgress(unittest.TestCase):
    def test_each_unit_reports_start_and_completion_while_the_run_is_in_progress(self):
        output = io.StringIO()
        unit = ("test_example", "test_example", Path("/repo/tests"), [])
        with (
            mock.patch.object(smoke_runner, "modules", return_value=[("test_example", Path("/repo/tests"), "test_example")]),
            mock.patch.object(smoke_runner, "plan", return_value=[unit]),
            mock.patch.object(smoke_runner, "load_timings", return_value={}),
            mock.patch.object(smoke_runner, "jobs", return_value=1),
            mock.patch.object(smoke_runner, "save_timings"),
            mock.patch.object(smoke_runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
        ):
            code = smoke_runner.run(Path("/repo"), out=output)

        self.assertEqual(0, code)
        lines = output.getvalue().splitlines()
        self.assertTrue(any("Smoke progress: starting 1 test unit" in line for line in lines))
        self.assertTrue(any("[RUN ] test_example" in line for line in lines))
        self.assertTrue(any("[ OK ] test_example (" in line for line in lines))
        self.assertTrue(any("all passed" in line for line in lines))

    def test_a_run_that_takes_long_prints_its_slowest_units_without_being_asked(self):
        """#1180: the slowest-module line shows after SHOW_SLOWEST_AFTER seconds, and a quick run stays quiet."""
        unit = ("test_example", "test_example", Path("/repo/tests"), [])
        for after, expected in ((0, True), (10 ** 6, False)):
            output = io.StringIO()
            with (
                mock.patch.object(smoke_runner, "modules", return_value=[("test_example", Path("/repo/tests"), "test_example")]),
                mock.patch.object(smoke_runner, "plan", return_value=[unit]),
                mock.patch.object(smoke_runner, "load_timings", return_value={}),
                mock.patch.object(smoke_runner, "jobs", return_value=1),
                mock.patch.object(smoke_runner, "save_timings"),
                mock.patch.object(smoke_runner, "SHOW_SLOWEST_AFTER", after),
                mock.patch.dict(smoke_runner.os.environ, {"OLIVERCODE_VALIDATE_TIMES": ""}),
                mock.patch.object(smoke_runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
            ):
                smoke_runner.run(Path("/repo"), out=output)
            self.assertEqual(expected, "slowest units: test_example" in output.getvalue())

    def test_a_full_run_leaves_the_push_time_module_out_and_says_so_and_a_round_or_the_env_keeps_it(self):
        """#1155: the drain canary runs at the push, so a full run names it as not run, and OLIVERCODE_CANARY=1 or a round that its code touches includes it."""
        mods = [("test_drain_canary", Path("/repo/tests"), "test_drain_canary"), ("test_example", Path("/repo/tests"), "test_example")]
        for env, changed, expected_ran in (({"OLIVERCODE_CANARY": ""}, None, False), ({"OLIVERCODE_CANARY": "1"}, None, True), ({"OLIVERCODE_CANARY": ""}, ["cmd_drain.py"], True)):
            output, seen = io.StringIO(), []
            def plan(selected, timings, workers):
                seen.extend(n for n, _, _ in selected)
                return [(n, m, f, []) for n, f, m in selected]
            with (
                mock.patch.object(smoke_runner, "modules", return_value=mods),
                mock.patch.object(smoke_runner, "affected", return_value=[mods[0]]),
                mock.patch.object(smoke_runner, "plan", side_effect=plan),
                mock.patch.object(smoke_runner, "load_timings", return_value={}),
                mock.patch.object(smoke_runner, "jobs", return_value=1),
                mock.patch.object(smoke_runner, "save_timings"),
                mock.patch.dict(smoke_runner.os.environ, env),
                mock.patch.object(smoke_runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
            ):
                smoke_runner.run(Path("/repo"), out=output, changed=changed)
            self.assertEqual(expected_ran, "test_drain_canary" in seen, env)
            self.assertEqual(not expected_ran and changed is None, "Not run here: test_drain_canary" in output.getvalue())

    def test_a_test_process_that_cannot_start_is_reported_as_a_failure(self):
        output = io.StringIO()
        unit = ("test_example", "test_example", Path("/repo/tests"), [])
        with (
            mock.patch.object(smoke_runner, "modules", return_value=[("test_example", Path("/repo/tests"), "test_example")]),
            mock.patch.object(smoke_runner, "plan", return_value=[unit]),
            mock.patch.object(smoke_runner, "load_timings", return_value={}),
            mock.patch.object(smoke_runner, "jobs", return_value=1),
            mock.patch.object(smoke_runner.subprocess, "run", side_effect=OSError("cannot execute")),
        ):
            code = smoke_runner.run(Path("/repo"), out=output)

        self.assertEqual(1, code)
        self.assertIn("[FAIL] test_example", output.getvalue())
        self.assertIn("Could not start test module: cannot execute", output.getvalue())


if __name__ == "__main__":
    unittest.main()
