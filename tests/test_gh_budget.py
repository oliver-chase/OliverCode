"""Tests for the shared GitHub rate-limit budget: scripts/lib/gh_budget.py and the gh_guard and gh_watch hooks."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import gh_budget  # noqa: E402

GUARD = REPO_ROOT / "scripts" / "hooks" / "gh_guard.py"
WATCH = REPO_ROOT / "scripts" / "hooks" / "gh_watch.py"


class Isolated(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook(self, script, payload):
        env = {**os.environ, "OLIVERCODE_HOME": str(self.home)}
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

    def test_run_returns_75_without_calling_github_while_held(self):
        gh_budget.note_limit()
        runner = mock.Mock()
        done = gh_budget.run(["issue", "list"], runner=runner)
        self.assertEqual(gh_budget.BLOCKED, done.returncode)
        runner.assert_not_called()

    def test_a_limit_in_an_answer_is_recorded_for_the_other_agents(self):
        failing = mock.Mock(return_value=subprocess.CompletedProcess([], 1, "", "GraphQL: API rate limit already exceeded"))
        gh_budget.run(["project", "item-list"], runner=failing)
        self.assertTrue(gh_budget.refusal())

    def test_a_read_within_the_ttl_is_not_asked_again(self):
        ok = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '{"items": []}', ""))
        gh_budget.run(["project", "item-list", "15"], ttl=60, runner=ok)
        again = gh_budget.run(["project", "item-list", "15"], ttl=60, runner=ok)
        self.assertEqual(1, ok.call_count)
        self.assertEqual('{"items": []}', again.stdout)


class TestWriteCap(Isolated):
    def test_writes_up_to_the_cap_pass_and_the_next_is_refused_with_a_time(self):
        with mock.patch.object(gh_budget, "WRITES_PER_HOUR", 3):
            self.assertEqual(["", "", ""], [gh_budget.reserve_write() for _ in range(3)])
            self.assertIn("3 GitHub writes in the last hour", gh_budget.reserve_write())

    def test_a_write_older_than_an_hour_no_longer_counts(self):
        with mock.patch.object(gh_budget, "WRITES_PER_HOUR", 1):
            gh_budget.reserve_write(now=time.time() - 3700)
            self.assertEqual("", gh_budget.reserve_write())


class TestHooks(Isolated):
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


if __name__ == "__main__":
    unittest.main()
