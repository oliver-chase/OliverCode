"""The regression evals replay fixed scenarios through the real guard hooks, and a mismatch fails the suite."""

import contextlib
import io
import json
import os
import stat
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import evals  # noqa: E402

WRONG = {"guard": "commit_guard", "scenarios": [
    {"name": "A deliberately wrong expectation", "repo": "gated", "expect": "allow",
     "payload": {"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}, "cwd": "{repo}"}}]}


def run_command(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = evals.command_eval(argv)
    return code, out.getvalue()


class TestScenarios(unittest.TestCase):
    def test_every_fixed_scenario_gets_the_verdict_it_expects(self):
        scenarios = evals.load()
        self.assertEqual([], evals.run_offline(scenarios))

    def test_each_guard_has_scenarios_that_block_and_scenarios_that_allow(self):
        by_guard = {}
        for sc in evals.load():
            by_guard.setdefault(sc["guard"], set()).add(sc["expect"])
        self.assertEqual({"commit_guard", "placement_guard", "policy_guard", "gh_guard", "archived_guard", "commit_msg", "reset_guard"}, set(by_guard))
        for guard, verdicts in by_guard.items():
            self.assertIn("allow", verdicts, guard)
            self.assertTrue(verdicts & {"deny", "ask"}, guard)

    def folder(self, data):
        folder = temp_dir(self)
        (folder / "wrong.json").write_text(json.dumps(data), encoding="utf-8")
        return folder

    def test_a_wrong_expectation_is_a_mismatch_and_exits_1(self):
        with mock.patch.object(evals, "EVAL_DIR", self.folder(WRONG)):
            code, printed = run_command([])
        self.assertEqual(1, code)
        self.assertIn("MISMATCH commit_guard: A deliberately wrong expectation: expected allow, got deny", printed)
        self.assertIn("0 of 1 scenarios match", printed)

    def test_a_hook_that_crashes_is_an_error_verdict_and_a_mismatch(self):
        hooks = temp_dir(self)
        (hooks / "crash.py").write_text("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n", encoding="utf-8")
        data = {"guard": "crash_guard", "entry": "crash.py", "scenarios": [{"name": "Crash", "repo": "gated", "expect": "allow", "payload": {}}]}
        with mock.patch.object(evals, "EVAL_DIR", self.folder(data)), mock.patch.object(evals, "HOOKS", hooks):
            code, printed = run_command([])
        self.assertEqual(1, code)
        self.assertIn("MISMATCH crash_guard: Crash: expected allow, got error (boom)", printed)

    def test_a_wrong_reason_is_a_mismatch(self):
        data = json.loads(json.dumps(WRONG))
        data["scenarios"][0].update(expect="deny", reason="a sentence the guard never says")
        with mock.patch.object(evals, "EVAL_DIR", self.folder(data)):
            code, printed = run_command([])
        self.assertEqual(1, code)
        self.assertIn("the reason lacks", printed)

    def test_a_deny_message_over_200_characters_or_with_no_docs_section_is_a_mismatch(self):
        data = json.loads(json.dumps(WRONG))
        data["scenarios"][0].update(expect="deny")
        for message, lacks in (("x" * 190 + " docs/RULES.md" + "y" * 10, "characters"), ("A message that names no section.", "docs/")):
            with mock.patch.object(evals, "EVAL_DIR", self.folder(data)), mock.patch.object(evals, "_hook_verdict", return_value=("deny", message)):
                code, printed = run_command([])
            self.assertEqual(1, code)
            self.assertIn(lacks, printed)

    def test_a_scenario_with_no_expectation_is_refused(self):
        data = {"guard": "commit_guard", "scenarios": [{"name": "x", "payload": {}}]}
        with self.assertRaises(ValueError):
            evals.load(folder=self.folder(data))

    def test_an_unknown_guard_exits_1(self):
        code, printed = run_command(["--guard", "no_such_guard"])
        self.assertEqual(1, code)
        self.assertIn("no scenarios for no_such_guard", printed)

    def test_guard_runs_only_that_guards_scenarios(self):
        code, printed = run_command(["--guard", "reset_guard"])
        self.assertEqual((0, True), (code, "5 of 5 scenarios match" in printed))


if __name__ == "__main__":
    unittest.main()
