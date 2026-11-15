"""Tests for the shared GitHub rate-limit budget: scripts/lib/gh_budget.py and the gh_guard and gh_watch hooks."""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import gh_budget  # noqa: E402

GUARD = REPO_ROOT / "scripts" / "hooks" / "gh_guard.py"
WATCH = REPO_ROOT / "scripts" / "hooks" / "gh_watch.py"


class Isolated(unittest.TestCase):
    hook_env: dict = {}

    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_GH_POINTS_FLOOR": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook(self, script, payload):
        env = {**os.environ, "OLIVERCODE_HOME": str(self.home), **self.hook_env}
        done = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), capture_output=True, text=True, env=env)
        return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else None


class TestLimitHold(Isolated):
    def test_nothing_is_held_at_first(self):
        self.assertEqual("", gh_budget.refusal())

    def test_a_noted_limit_holds_every_caller_until_the_time_named(self):
        until = gh_budget.note_limit(seconds=600)
        self.assertIn(time.strftime("%H:%M", time.localtime(until)), gh_budget.refusal())

    def test_a_longer_hold_is_never_shortened(self):
        long = gh_budget.note_limit(seconds=1000)
        self.assertEqual(long, gh_budget.note_limit(seconds=10))

    def test_clear_lifts_the_hold(self):
        gh_budget.note_limit()
        gh_budget.clear()
        self.assertEqual("", gh_budget.refusal())


class TestWriteCap(Isolated):
    def test_writes_up_to_the_cap_pass_and_the_next_is_refused_with_a_time(self):
        with mock.patch.object(gh_budget, "WRITES_PER_HOUR", 3):
            self.assertEqual(["", "", ""], [gh_budget.reserve_write() for _ in range(3)])
            self.assertIn("3 GitHub writes in the last hour", gh_budget.reserve_write())

    def test_a_write_older_than_an_hour_no_longer_counts(self):
        with mock.patch.object(gh_budget, "WRITES_PER_HOUR", 1):
            gh_budget.reserve_write(now=time.time() - 3700)
            self.assertEqual("", gh_budget.reserve_write())


class TestCallCap(Isolated):
    def test_calls_up_to_the_cap_pass_and_the_next_names_the_seconds_to_wait(self):
        with mock.patch.object(gh_budget, "CALLS_PER_MINUTE", 2):
            now = time.time()
            self.assertEqual(["", ""], [gh_budget.reserve_call(now=now) for _ in range(2)])
            self.assertIn("Try again in 60 seconds", gh_budget.reserve_call(now=now))

    def test_a_call_older_than_a_minute_no_longer_counts(self):
        with mock.patch.object(gh_budget, "CALLS_PER_MINUTE", 1):
            gh_budget.reserve_call(now=time.time() - 61)
            self.assertEqual("", gh_budget.reserve_call())


class TestPointsReserve(Isolated):
    def test_points_under_the_floor_hold_every_caller_until_the_reset(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            why = gh_budget.points_refusal(fetch=lambda: {"remaining": 120, "reset": time.time() + 600})
        self.assertIn("120", why)

    def test_points_above_the_floor_pass_and_the_reading_is_cached(self):
        calls = []
        fetch = lambda: calls.append(1) or {"remaining": 4000, "reset": time.time() + 600}
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            self.assertEqual("", gh_budget.points_refusal(fetch=fetch))
            self.assertEqual("", gh_budget.points_refusal(fetch=fetch))
        self.assertEqual(1, len(calls))

    def test_a_failed_reading_fails_open(self):
        def boom():
            raise OSError("no gh")
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            self.assertEqual("", gh_budget.points_refusal(fetch=boom))

    def test_the_guard_denies_a_gh_call_when_the_cached_reading_is_low(self):
        (self.home / "gh-points.json").write_text(json.dumps({"at": time.time(), "remaining": 50, "reset": time.time() + 600}))
        self.hook_env = {"OLIVERCODE_GH_POINTS_FLOOR": "500"}
        out = self.hook(GUARD, {"tool_input": {"command": "gh issue list"}})
        self.assertIn("50 GraphQL points", out["permissionDecisionReason"])


class TestHooks(Isolated):
    def test_a_per_field_item_edit_is_denied_and_points_at_the_batch_script(self):
        out = self.hook(GUARD, {"tool_input": {"command": "gh project item-edit --id X --field-id F"}})
        self.assertIn("batch_project.py", out["permissionDecisionReason"])

    def test_a_gh_command_passes_when_nothing_is_held(self):
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh issue list"}}))

    def test_a_gh_command_is_denied_while_held_and_says_until_when(self):
        gh_budget.note_limit()
        out = self.hook(GUARD, {"tool_input": {"command": "cd x && gh project item-list 15"}})
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("Hold all gh calls until about", out["permissionDecisionReason"])

    def test_a_script_that_calls_gh_is_denied_while_held(self):
        gh_budget.note_limit()
        out = self.hook(GUARD, {"tool_input": {"command": "python3 skills/backlog/scripts/complete_story.py --story 5"}})
        self.assertEqual("deny", out["permissionDecision"])

    def test_the_batching_script_passes_a_hold_so_it_can_queue_without_a_gh_call(self):
        gh_budget.note_limit()
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "python3 skills/backlog/scripts/batch_project.py --input work.json"}}))

    def test_the_free_rate_limit_query_and_other_commands_always_pass(self):
        gh_budget.note_limit()
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh api rate_limit"}}))
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "ls -la"}}))

    def test_a_watched_limit_in_any_output_holds_the_other_agents(self):
        self.hook(WATCH, {"tool_input": {"command": "gh issue close 5"},
                          "tool_response": {"stderr": "GraphQL: API rate limit already exceeded for user ID 1."}})
        self.assertTrue(gh_budget.refusal())

    def test_ordinary_output_records_nothing(self):
        self.hook(WATCH, {"tool_input": {"command": "gh issue list"}, "tool_response": {"stdout": "#1 a story"}})
        self.assertEqual("", gh_budget.refusal())

    def test_writes_count_against_the_cap_and_reads_do_not(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_WRITES_PER_HOUR": "1"}):
            self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh issue list"}}))
            self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh issue close 5"}}))
            out = self.hook(GUARD, {"tool_input": {"command": "gh issue comment 6 -b hi"}})
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("writes in the last hour", out["permissionDecisionReason"])

    def test_garbage_input_fails_open(self):
        done = subprocess.run([sys.executable, str(GUARD)], input="nope", capture_output=True, text=True)
        self.assertEqual((0, ""), (done.returncode, done.stdout))




class TestUsesGh(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        self.uses = gh_guard.uses_gh

    def test_reading_or_searching_a_script_that_calls_gh_is_not_a_gh_call(self):
        self.assertFalse(self.uses("sed -n 1,20p skills/backlog/scripts/complete_story.py"))
        self.assertFalse(self.uses("grep -n def skills/backlog/scripts/check_qa_signoff.py && ls"))

    def test_running_it_through_an_interpreter_or_wrapper_is(self):
        self.assertTrue(self.uses("cd x && python3 skills/backlog/scripts/complete_story.py --story 1"))
        self.assertTrue(self.uses("timeout 30 gh issue list"))
        self.assertTrue(self.uses("echo $(gh issue list)"))

    def test_the_batching_script_does_not_hide_a_gh_call_beside_it(self):
        self.assertFalse(self.uses("python3 skills/backlog/scripts/batch_project.py --input w.json"))
        self.assertTrue(self.uses("python3 skills/backlog/scripts/batch_project.py --input w.json && gh issue close 1"))


class TestIsWrite(unittest.TestCase):
    def test_reading_a_write_script_is_not_a_write_and_running_it_is(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        self.assertFalse(gh_guard.is_write("cat skills/backlog/scripts/log_action.py"))
        self.assertTrue(gh_guard.is_write("cd x && python3 skills/backlog/scripts/log_action.py --story 1"))
        for command in ("gh -R o/r issue close 3", 'bash -c "gh pr merge 1"', "olivercode backlog-setup --apply"):
            self.assertTrue(gh_guard.is_write(command), command)
            self.assertTrue(gh_guard.uses_gh(command), command)
        self.assertFalse(gh_guard.is_write("gh -R o/r issue list"))


if __name__ == "__main__":
    unittest.main()
