"""Validation throughput (#757): the parallel gate runner, the per-run timeout and retry, the queue bypass gate
and the smoke runner (scripts/lib/validate_gates.py, queue_bypass.py, smoke_runner.py)."""

import io
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import queue_bypass  # noqa: E402
import smoke_runner  # noqa: E402
import validate_gates  # noqa: E402


def run(gates, **kw):
    out, err = io.StringIO(), io.StringIO()
    code = validate_gates.run_gates(gates, out=out, err=err, **kw)
    return code, out.getvalue(), err.getvalue()


class ParallelGates(unittest.TestCase):
        def test_round_gate_scope_is_risk_proportional_and_full_gate_list_is_unchanged(self):
            import sys
            sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
            import validation_scope
            self.assertEqual(["precommit"], validation_scope.round_gates(["README.txt"]))
            self.assertEqual(["precommit", "quality", "smoke"], validation_scope.round_gates(["scripts/lib/thing.py", "tests/test_thing.py"]))
            self.assertEqual(["precommit", "refs", "docs"], validation_scope.round_gates(["docs/guide.md"]))
            self.assertEqual(["precommit", "bypass", "hookstate"], validation_scope.round_gates(["scripts/validate.sh"]))
            self.assertIn("GATES=(precommit fleet bloat quality refs docs limits bypass smoke hookstate)", (REPO_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8"))
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

    def test_a_gate_that_exits_reports_its_real_exit_code(self):
        real_sleep = validate_gates.time.sleep
        with mock.patch.object(validate_gates.time, "sleep", lambda _s: real_sleep(0.8)):  # the gate exits while the loop sleeps past the 0.5s deadline
            code, out, err = run([("quick", "exit 3")], timeout=0.5)
        self.assertNotIn("stalled", out)
        self.assertEqual(3, code)

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
        self.assertFalse(hasattr(validate_gates, "default_retries"))
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_GATES": "3"}):
            self.assertEqual(3, validate_gates.default_max_gates())

    def test_validate_sh_lists_each_gate_once_and_runs_one_by_name(self):
        text = (REPO_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn("GATES=(precommit fleet bloat quality refs docs limits bypass smoke hookstate)", text)
        import subprocess
        done = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "validate.sh"), "--gate", "nonesuch"], capture_output=True, text=True)
        self.assertEqual(2, done.returncode)


class QueueBypassGate(unittest.TestCase):
    def repo_with(self, files):
        repo = scratch_repo(temp_dir(self, "olivercode-bypass-"))
        for rel, text in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            git(repo, "add", rel)
        return repo

    def test_this_repo_has_no_bypass(self):
        self.assertEqual([], queue_bypass.check(REPO_ROOT))

    def test_a_mention_of_the_queue_in_a_comment_or_an_env_value_does_not_queue_the_line(self):
        for line in ("pytest  # validate_queue run", 'echo "validate_queue run"; pytest', "VALIDATE_QUEUE_SLOT=none pytest", "echo validate_queue; npm test"):
            repo = self.repo_with({"scripts/nightly.sh": f"#!/usr/bin/env bash\n{line}\n"})
            self.assertEqual(1, len(queue_bypass.check(repo)), line)

    def test_a_quoted_or_variable_path_to_the_queue_passes(self):
        for line in ('python3 "$validate_queue" run -- pytest', "python3 $validate_queue run -- pytest"):
            repo = self.repo_with({"scripts/nightly.sh": f"#!/usr/bin/env bash\n{line}\n"})
            self.assertEqual([], queue_bypass.check(repo), line)

    def test_a_line_that_runs_the_queue_passes(self):
        repo = self.repo_with({"scripts/nightly.sh": "#!/usr/bin/env bash\nvalidate-queue run -- pytest\n"})
        self.assertEqual([], queue_bypass.check(repo))

    def test_git_failing_fails_the_gate_and_names_the_cause(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = queue_bypass.main(["/nonexistent-olivercode-path"])
        self.assertEqual(1, code)
        self.assertIn("unknown", out.getvalue())

    def test_a_script_that_runs_the_suite_directly_is_named_with_the_entry_point(self):
        repo = self.repo_with({"scripts/nightly.sh": "#!/usr/bin/env bash\npython3 -m unittest discover -s tests\n"})
        found = queue_bypass.check(repo)
        self.assertEqual(1, len(found))
        self.assertIn("scripts/nightly.sh:2", found[0])
        self.assertIn("bash scripts/validate.sh", found[0])

    def test_a_python_caller_that_builds_an_unqueued_argv_is_caught(self):
        repo = self.repo_with({"tools/run.py": 'import subprocess\nsubprocess.run(["python3", "-m", "unittest"])\n'})
        self.assertEqual(1, len(queue_bypass.check(repo)))

    def test_a_validate_sh_without_the_queue_block_is_caught(self):
        repo = self.repo_with({"scripts/validate.sh": "#!/usr/bin/env bash\necho hi\n"})
        self.assertIn("no queue block", queue_bypass.check(repo)[0])

    def test_validate_sh_started_with_the_slot_variables_replaced_is_caught(self):
        repo = self.repo_with({"scripts/ci.sh": "VALIDATE_QUEUE_SLOT=none bash scripts/validate.sh\n"})
        self.assertIn("scripts/ci.sh:1", queue_bypass.check(repo)[0])

    def test_a_queued_command_a_comment_a_test_and_a_doc_pass(self):
        repo = self.repo_with({
            "scripts/ok.sh": "# python3 -m unittest is run by validate.sh\nvalidate-queue run python3 -m unittest\n"
                             "python3 validate_queue.py run \\\n  python3 -m unittest\n",
            "tests/test_x.py": 'x = "python3 -m unittest"\n',
            "docs/NOTES.md": "run python3 -m unittest\n",
        })
        self.assertEqual([], queue_bypass.check(repo))

    def test_the_gate_exits_one_and_prints_each_bypass(self):
        repo = self.repo_with({"scripts/x.sh": "pytest\n"})
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(1, queue_bypass.main([str(repo)]))
        self.assertIn("scripts/x.sh:1", out.getvalue())


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

    def test_changed_files_select_only_the_modules_that_cover_them(self):
        """#1142: a round check narrows to the modules that import or name a changed file, and names which it picked."""
        root = self.make("pass")
        (root / "tests" / "test_b.py").write_text(
            "import unittest\n\n\ndef helper():\n    return 'cmd_land'\n\n\nclass T(unittest.TestCase):\n    def test_y(self):\n        pass\n",
            encoding="utf-8")
        out = io.StringIO()
        self.assertEqual(0, smoke_runner.run(root, out, changed=["scripts/lib/cmd_land.py"]))
        text = out.getvalue()
        self.assertIn("1 of 2 modules cover the changed files: test_b", text)
        self.assertIn("Ran 1 tests across 1 modules, all passed", text)

    def test_no_module_covering_the_changed_files_runs_the_full_suite(self):
        """#1142: a changed file no test module names falls back to the whole suite."""
        out = io.StringIO()
        self.assertEqual(0, smoke_runner.run(self.make("pass"), out, changed=["docs/NOTES.md"]))
        self.assertIn("running the full suite", out.getvalue())
        self.assertIn("Ran 1 tests across 1 modules, all passed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
