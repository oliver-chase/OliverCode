"""Validation throughput (#757): the parallel gate runner, the per-run timeout and retry, and the smoke runner (scripts/lib/validate_gates.py, smoke_runner.py)."""

import io
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import smoke_runner  # noqa: E402
import validate_gates  # noqa: E402


def run(gates, **kw):
    out, err = io.StringIO(), io.StringIO()
    code = validate_gates.run_gates(gates, out=out, err=err, **kw)
    return code, out.getvalue(), err.getvalue()


class ParallelGates(unittest.TestCase):
    def test_output_replays_in_the_order_given_even_when_a_later_gate_finishes_first(self):
        code, out, _ = run([("slow", "sleep 0.6; echo slow-done"), ("fast", "echo fast-done")], timeout=20)
        self.assertEqual(0, code)
        self.assertLess(out.index("slow-done"), out.index("fast-done"))

    def test_any_failing_gate_fails_the_run_with_its_exit_code_and_every_gate_still_reports(self):
        code, out, _ = run([("a", "echo a-out"), ("b", "echo b-out; exit 3"), ("c", "echo c-out; exit 5")], timeout=20)
        self.assertEqual(3, code)
        for word in ("a-out", "b-out", "c-out"):
            self.assertIn(word, out)

    def test_gates_overlap_in_time(self):
        import time
        began = time.monotonic()
        code, _, _ = run([(f"g{i}", "sleep 1") for i in range(4)], timeout=20)
        self.assertEqual(0, code)
        self.assertLess(time.monotonic() - began, 3.0)

    def test_a_stalled_gate_is_stopped_once_named_and_never_started_again(self):
        """#1072: a gate past the budget fails the run with exit 124 and its name, and no retry starts it a second time."""
        marker = temp_dir(self) / "starts"
        code, out, err = run([("ok", "echo fine"), ("hangs", f'echo x >> "{marker}"; sleep 60')], timeout=0.6)
        self.assertEqual(validate_gates.TIMEOUT_EXIT, code)
        self.assertIn("fine", out)
        self.assertIn("stalled gate 'hangs'", out)
        self.assertIn("'hangs' still running after", err)
        self.assertEqual(1, len(marker.read_text().split()))
        self.assertNotIn("again", err)

    def test_the_timeout_comes_from_the_environment_and_scales_with_load(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_TIMEOUT": "123"}):
            self.assertEqual(123, validate_gates.default_timeout())
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_TIMEOUT": ""}), mock.patch("os.cpu_count", return_value=8), \
                mock.patch("os.getloadavg", return_value=(1.0, 0, 0)):
            self.assertEqual(validate_gates.BASE_BUDGET, validate_gates.default_timeout())
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_TIMEOUT": ""}), mock.patch("os.cpu_count", return_value=8), \
                mock.patch("os.getloadavg", return_value=(40.0, 0, 0)):
            self.assertEqual(validate_gates.BASE_BUDGET * validate_gates.MAX_SCALE, validate_gates.default_timeout())

    def test_each_gate_prints_a_line_when_it_starts_and_when_it_finishes_and_its_output_still_replays(self):
        code, out, err = run([("one", "echo one-out"), ("two", "echo two-out; exit 4")], timeout=20)
        self.assertEqual(4, code)
        self.assertIn("=== validate: gate 'one' started", err)
        self.assertRegex(err, r"=== validate: gate 'one' passed in \d+s ===")
        self.assertRegex(err, r"=== validate: gate 'two' failed \(exit 4\) in \d+s ===")
        self.assertLess(out.index("one-out"), out.index("two-out"))
        self.assertNotIn("started", out)

    def test_a_run_past_its_budget_fails_and_names_the_gate_still_running_with_the_load(self):
        code, _, err = run([("quick", "true"), ("slow", "sleep 60")], timeout=1.0)
        self.assertEqual(validate_gates.TIMEOUT_EXIT, code)
        self.assertRegex(err, r"gate 'slow' still running after \d+s at the 1s budget .*load [\d.]+ on \d+ cores")
        self.assertIn("bash scripts/validate.sh --gate slow", err)
        self.assertNotIn("again", err)

    def test_at_most_max_gates_run_at_once_and_the_rest_wait_their_turn(self):
        import time
        began = time.monotonic()
        code, _, err = run([(f"g{i}", "sleep 0.5") for i in range(4)], timeout=20, max_gates=2)
        self.assertEqual(0, code)
        self.assertGreaterEqual(time.monotonic() - began, 1.0)
        self.assertIn("'g1' started (2 running, 2 waiting)", err)
        self.assertNotIn("(3 running", err)
        self.assertIn("at most 2 at once", err)

    def test_gates_the_budget_never_reached_are_named_and_fail_the_run(self):
        code, out, err = run([("hangs", "sleep 60"), ("later", "echo later-out")], timeout=0.6, max_gates=1)
        self.assertEqual(validate_gates.TIMEOUT_EXIT, code)
        self.assertIn("never started before the budget: later", err)
        self.assertIn("stalled gate 'later'", out)

    def test_the_gate_cap_defaults_to_the_core_count(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_GATES": ""}), mock.patch("os.cpu_count", return_value=8):
            self.assertEqual(8, validate_gates.default_max_gates())
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_GATES": "0.5"}):
            self.assertEqual(1, validate_gates.default_max_gates())  # a cap under one still runs one gate
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_GATES": "3"}):
            self.assertEqual(3, validate_gates.default_max_gates())

    def test_validate_sh_lists_each_gate_once_and_runs_one_by_name(self):
        text = (REPO_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn("GATES=(precommit fleet bloat quality refs docs limits smoke)", text)
        import subprocess
        done = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "validate.sh"), "--gate", "nonesuch"], capture_output=True, text=True)
        self.assertEqual(2, done.returncode)


class SmokeRunner(unittest.TestCase):
    def make(self, body):
        root = temp_dir(self, "olivercode-smoke-")
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text(
            f"import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        {body}\n", encoding="utf-8")
        return root

    def test_a_passing_module_is_counted(self):
        out = io.StringIO()
        self.assertEqual(0, smoke_runner.run(self.make("pass"), out))
        self.assertIn("Ran 1 tests across 1 modules, all passed", out.getvalue())

    def test_a_failing_module_is_replayed_and_fails_the_run(self):
        out = io.StringIO()
        self.assertEqual(1, smoke_runner.run(self.make("self.fail('boom')"), out))
        self.assertIn("--- test_a ---", out.getvalue())
        self.assertIn("boom", out.getvalue())

    def test_parallelism_comes_from_the_core_count_and_can_be_overridden(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_JOBS": ""}), mock.patch("os.cpu_count", return_value=12):
            self.assertEqual(12, smoke_runner.jobs())
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_JOBS": "3"}):
            self.assertEqual(3, smoke_runner.jobs())


if __name__ == "__main__":
    unittest.main()
