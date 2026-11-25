"""Tests for the shared GitHub rate-limit budget: scripts/lib/gh_budget.py and the gh_guard and gh_watch hooks."""

import fcntl
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, run_hook, temp_dir

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
        done = run_hook(script, payload, env=env)
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

    def test_a_reading_older_than_the_ttl_is_fetched_again(self):
        calls = []
        fetch = lambda: calls.append(1) or {"remaining": 4000, "reset": time.time() + 600}
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            now = time.time()
            gh_budget.points_refusal(fetch=fetch, now=now)
            gh_budget.points_refusal(fetch=fetch, now=now + gh_budget.POINTS_TTL - 1)
            self.assertEqual(1, len(calls))
            gh_budget.points_refusal(fetch=fetch, now=now + gh_budget.POINTS_TTL + 1)
        self.assertEqual(2, len(calls))

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

    def test_a_rest_call_passes_the_points_hold_that_stops_a_graphql_call(self):
        (self.home / "gh-points.json").write_text(json.dumps({"at": time.time(), "remaining": 50, "reset": time.time() + 600}))
        self.hook_env = {"OLIVERCODE_GH_POINTS_FLOOR": "500"}
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh api repos/o/r/issues/1"}, "tool_use_id": "t"}))
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh api -X PATCH repos/o/r/issues/1 -f state=closed"}}))
        self.assertTrue(self.hook(GUARD, {"tool_input": {"command": "gh api graphql -f query=x"}}))
        pending = json.loads((self.home / "gh-pending.json").read_text())
        self.assertEqual(["t"], list(pending), "only the REST call under its tool id is costed, and the refused GraphQL call is not")


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
        self.assertIn("until about", out["permissionDecisionReason"])

    def test_a_mixed_git_and_gh_command_refuses_only_the_gh_step_while_held(self):
        gh_budget.note_limit()
        out = self.hook(GUARD, {"tool_input": {"command": "git add a.txt && gh issue close 5 && git status\ncd x; gh pr list"}})
        self.assertEqual("ask", out["permissionDecision"])
        run = subprocess.run(["bash", "-c", out["updatedInput"]["command"].replace("git add a.txt", "echo ADD").replace("git status", "echo STATUS")
                              .replace("cd x", "true")], capture_output=True, text=True)
        self.assertIn("ADD", run.stdout)
        self.assertIn("STATUS", run.stdout)  # a git step after the refused gh step still runs
        self.assertEqual(2, run.stderr.count("until about"))
        for command in ("git status | gh issue list", "git log $(gh issue list)", "gh issue list"):  # not safely splittable, or no git step
            self.assertEqual("deny", self.hook(GUARD, {"tool_input": {"command": command}})["permissionDecision"], command)

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

    def test_each_limit_wording_holds_the_other_agents(self):
        for text in ("You have exceeded a secondary rate limit.", "abuse detection mechanism triggered", "graphql_rate_limit"):
            with self.subTest(text=text):
                self.hook(WATCH, {"tool_input": {"command": "gh issue close 5"}, "tool_response": {"stderr": text}})
                self.assertTrue(gh_budget.refusal())
                gh_budget.clear()

    def test_printing_the_guards_own_source_records_nothing(self):
        source = 'LIMIT_TEXT = re.compile(r"rate limit (already )?exceeded|secondary rate limit|abuse detection")'
        self.hook(WATCH, {"tool_input": {"command": "grep -n LIMIT_TEXT scripts/lib/gh_budget.py"},
                          "tool_response": {"stdout": source}})
        self.assertEqual("", gh_budget.refusal())

    def test_printing_a_file_that_quotes_a_gh_error_records_nothing(self):
        quoted = '   146\t                          "tool_response": {"stderr": "gh: API rate limit already exceeded for user ID 1."}})'
        self.hook(WATCH, {"tool_input": {"command": "cat -n tests/test_gh_budget.py"}, "tool_response": {"stdout": quoted}})
        self.assertEqual("", gh_budget.refusal())

    def test_a_script_that_hits_the_limit_still_holds_the_other_agents(self):
        self.hook(WATCH, {"tool_input": {"command": "python3 scripts/batch_project.py --input -"},
                          "tool_response": {"stderr": "gh: API rate limit already exceeded for user ID 1."}})
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




class TestCostLog(Isolated):
    def setUp(self):
        super().setUp()
        # The readings are cached for POINTS_TTL, so a zero TTL makes each call read the figures its test gives it.
        patcher = mock.patch.object(gh_budget, "POINTS_TTL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def points(self, left, rest=None):
        return lambda: {"remaining": left, "reset": 0, **({} if rest is None else {"rest": rest})}

    def test_a_finished_call_logs_the_points_it_spent(self):
        gh_budget.note_before("k1", fetch=self.points(4000), now=100)
        gh_budget.note_after("k1", "s1", "gh project item-list 15", fetch=self.points(3950), now=101)
        rows = gh_budget._read_rows(102, 3600)
        self.assertEqual([(r["session"], r["points"]) for r in rows], [("s1", 50)])
        self.assertIn("item-list", rows[0]["cmd"])

    def test_a_call_made_in_a_story_worktree_logs_its_story(self):
        gh_budget.note_before("k2", fetch=self.points(4000), now=100)
        with mock.patch.object(gh_budget.failure_log, "story_of", return_value=1204):
            gh_budget.note_after("k2", "s1", "gh issue view 1", fetch=self.points(3990), now=101, cwd="/wt")
        gh_budget.note_before("k3", fetch=self.points(3990), now=102)
        gh_budget.note_after("k3", "s1", "gh issue view 2", fetch=self.points(3980), now=103)
        rows = gh_budget._read_rows(104, 3600)
        self.assertEqual([1204, None], [r.get("story") for r in rows])

    def test_a_session_over_its_share_is_held_while_others_are_active(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            for n, (key, session, spent) in enumerate((("a", "busy", 3000), ("b", "quiet", 10))):
                gh_budget.note_before(key, fetch=self.points(5000), now=100 + 2 * n)
                gh_budget.note_after(key, session, "gh x", fetch=self.points(5000 - spent), now=101 + 2 * n)
            self.assertIn("over its share", gh_budget.share_refusal("busy", now=110))
            self.assertEqual("", gh_budget.share_refusal("quiet", now=110))

    def test_one_active_session_may_use_the_whole_budget(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_POINTS_FLOOR": "500"}):
            gh_budget.note_before("a", fetch=self.points(5000), now=100)
            gh_budget.note_after("a", "solo", "gh x", fetch=self.points(2000), now=101)
            self.assertEqual("", gh_budget.share_refusal("solo", now=102))

    def test_a_line_older_than_a_day_is_dropped_when_a_new_one_is_written(self):
        gh_budget.note_before("a", fetch=self.points(5000), now=100)
        gh_budget.note_after("a", "s1", "gh old", fetch=self.points(4990), now=101)
        gh_budget.note_before("b", fetch=self.points(5000), now=100 + 90000)
        gh_budget.note_after("b", "s1", "gh new", fetch=self.points(4990), now=100 + 90001)
        lines = (gh_budget.home() / gh_budget.COST_LOG).read_text().splitlines()
        self.assertEqual(1, len(lines))
        self.assertIn("gh new", lines[0])


class TestPointsReading(Isolated):
    def test_a_minute_holds_one_rate_limit_call_however_many_gh_calls_run(self):
        reading = {"remaining": 4000, "reset": 0, "rest": 4900}
        with mock.patch.object(gh_budget, "_fetch_points", return_value=reading) as fetch:
            for n in range(5):
                gh_budget.note_before(f"k{n}", now=100 + n)
                gh_budget.note_after(f"k{n}", "s1", "gh x", now=100 + n)
            self.assertEqual(1, fetch.call_count)
            gh_budget.note_before("late", now=100 + gh_budget.POINTS_TTL + 1)
            self.assertEqual(2, fetch.call_count)


class TestGuardCheck(Isolated):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        self.guard = gh_guard

    def test_a_gh_call_that_may_run_is_costed_under_its_tool_call_id(self):
        with mock.patch.object(gh_budget, "note_before") as noted:
            self.assertEqual("", self.guard.check({"tool_input": {"command": "gh issue list"}, "session_id": "s", "tool_use_id": "t1"}))
        noted.assert_called_once_with("t1")

    def test_a_rest_call_is_costed_too(self):
        with mock.patch.object(gh_budget, "note_before") as noted:
            self.assertEqual("", self.guard.check({"tool_input": {"command": "gh api repos/o/r/issues/5"}, "session_id": "s", "tool_use_id": "t4"}))
        noted.assert_called_once_with("t4")

    def test_a_command_that_runs_no_gh_is_not_costed(self):
        with mock.patch.object(gh_budget, "note_before") as noted:
            self.guard.check({"tool_input": {"command": "grep -n LIMIT_TEXT scripts/lib/gh_budget.py"}, "tool_use_id": "t2"})
        noted.assert_not_called()

    def test_a_held_call_is_refused_and_not_costed(self):
        gh_budget.note_limit()
        with mock.patch.object(gh_budget, "note_before") as noted:
            self.assertTrue(self.guard.check({"tool_input": {"command": "gh issue list"}, "tool_use_id": "t3"}))
        noted.assert_not_called()


class TestUsesGh(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        self.uses = gh_guard.uses_gh

    def test_a_heredoc_body_is_text_and_not_a_gh_call(self):
        command = "python3 - <<'EOF'\ngh issue list\ncheck_board_hygiene.py --config x\nEOF"
        self.assertFalse(self.uses(command))

    def test_a_gh_call_after_a_heredoc_is_still_seen(self):
        command = "cat <<EOF\nplain text\nEOF\ngh issue list"
        self.assertTrue(self.uses(command))

    def test_a_gh_call_before_a_heredoc_is_still_seen(self):
        self.assertTrue(self.uses("gh issue create --body-file - <<'EOF'\nbody\nEOF"))

    def test_reading_or_searching_a_script_that_calls_gh_is_not_a_gh_call(self):
        self.assertFalse(self.uses("sed -n 1,20p skills/backlog/scripts/complete_story.py"))
        self.assertFalse(self.uses("grep -n def skills/backlog/scripts/check_board_hygiene.py && ls"))

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

    def test_release_repo_review_workflow_and_label_calls_are_writes(self):
        """#899: each of these changes GitHub, so each counts against the write budget."""
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        for command in ("gh release create v1", "gh repo delete o/r --yes", "gh pr review 3 --approve", "gh workflow run ci.yml",
                        "gh label create bug", "gh -R o/r release delete v1", "gh run rerun 9"):
            self.assertTrue(gh_guard.is_write(command), command)
        for command in ("gh release list", "gh repo view o/r", "gh pr view 3", "gh workflow list", "gh label list"):
            self.assertFalse(gh_guard.is_write(command), command)

    def test_a_write_hidden_in_a_subshell_or_given_by_flag_value_is_a_write(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        for command in ("x=$(gh pr merge 12)", "echo `gh pr merge 12`", "gh api repos/o/r/issues/1 --method=PATCH",
                        "gh api repos/o/r/issues --input body.json"):
            self.assertTrue(gh_guard.is_write(command), command)
        self.assertFalse(gh_guard.is_write("gh api repos/o/r --method=GET"))

    def test_a_graphql_query_is_a_read_and_a_mutation_is_a_write(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import gh_guard
        self.assertFalse(gh_guard.is_write('gh api graphql -f query="{ repository(owner: \\"o\\") { id } }"'))
        self.assertTrue(gh_guard.is_write('gh api graphql -f query="mutation{ x }"'))


class TestReplay(Isolated):
    """#1045: the replay sends each queued write once, keeps a failed one and counts its failures, and moves a write that keeps
    failing to the owner queue. A write queued during a replay is never lost."""

    def queue(self, *numbers):
        for n in numbers:
            gh_budget.enqueue(["gh", "issue", "close", str(n)], cwd=str(self.home))

    def rows(self):
        path = self.home / gh_budget.QUEUE
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_a_sent_write_is_never_sent_again_and_a_failed_one_is_retried(self):
        self.queue(1, 2, 3)
        calls = []

        def run(argv, cwd):
            calls.append(argv[-1])
            return subprocess.CompletedProcess([], 1 if argv[-1] == "3" else 0, "", "boom")

        gh_budget.replay(run=run)
        gh_budget.replay(run=run)
        self.assertEqual(["1", "2", "3", "3"], calls)
        (row,) = self.rows()
        self.assertEqual("3", row["argv"][-1])
        self.assertEqual(2, row["attempts"])

    def test_a_write_that_fails_three_times_moves_to_the_owner_queue(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        self.queue(5)
        bad = subprocess.CompletedProcess([], 1, "", "could not close")
        for _ in range(3):
            gh_budget.replay(run=lambda a, c: bad)
        self.assertEqual([], self.rows())
        self.assertIn("gh issue close 5", (self.home / "owner-queue.jsonl").read_text())

    def test_a_write_queued_during_a_replay_stays_queued(self):
        self.queue(1)

        def run(argv, cwd):
            if argv[-1] == "1":
                self.queue(2)
            return subprocess.CompletedProcess([], 0, "", "")

        gh_budget.replay(run=run)
        self.assertEqual(["2"], [row["argv"][-1] for row in self.rows()])

    def test_a_replay_that_starts_while_another_runs_sends_nothing(self):
        self.queue(1)
        calls = []
        with open(self.home / gh_budget.REPLAY_LOCK, "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            report = gh_budget.replay(run=lambda a, c: calls.append(a) or subprocess.CompletedProcess([], 0, "", ""))
        self.assertIn("Another replay", report)
        self.assertEqual([], calls)
        self.assertEqual(1, len(self.rows()))

    def test_a_command_that_raises_stays_queued_and_counts_a_failure(self):
        self.queue(4)

        def run(argv, cwd):
            raise subprocess.TimeoutExpired(argv, 120)

        self.assertIn("kept: gh issue close 4", gh_budget.replay(run=run))
        self.assertEqual(1, self.rows()[0]["attempts"])

    def test_a_rate_limit_stops_the_run_and_counts_no_failure(self):
        self.queue(1, 2)
        calls = []
        limited = subprocess.CompletedProcess([], 1, "", "API rate limit exceeded")
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_PROBE": "0"}):
            gh_budget.replay(run=lambda a, c: calls.append(a[-1]) or limited)
        self.assertEqual(["1"], calls)
        self.assertEqual([("1", None), ("2", None)], [(row["argv"][-1], row.get("attempts")) for row in self.rows()])


class TestResourceHold(Isolated):
    """The 2026-11-21 case: GraphQL at 0 while REST had 4892 calls left blocked every gh call until the reset (#669)."""

    def _graphql_out(self):
        self.hook(WATCH, {"tool_input": {"command": "gh issue close 783"},
                          "tool_response": {"stderr": "GraphQL: API rate limit already exceeded for user ID 1."}})

    def test_a_graphql_limit_holds_graphql_calls_and_rest_calls_still_run(self):
        self._graphql_out()
        denied = self.hook(GUARD, {"tool_input": {"command": "gh issue close 783"}})
        self.assertIn("GraphQL rate limit", denied["permissionDecisionReason"])
        self.assertIn("REST calls still run", denied["permissionDecisionReason"])
        self.assertIn("gh-limit queue", denied["permissionDecisionReason"])
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh api -X PATCH repos/o/r/issues/783 -f state=closed"}}))
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh api repos/o/r/issues/783"}}))

    def test_a_secondary_limit_holds_both(self):
        self.hook(WATCH, {"tool_input": {"command": "gh api repos/o/r/issues"}, "tool_response": {"stderr": "You have exceeded a secondary rate limit."}})
        self.assertTrue(self.hook(GUARD, {"tool_input": {"command": "gh api repos/o/r/issues/1"}}))
        self.assertTrue(self.hook(GUARD, {"tool_input": {"command": "gh issue list"}}))

    def test_a_rest_limit_leaves_graphql_free(self):
        self.hook(WATCH, {"tool_input": {"command": "gh api repos/o/r/issues"}, "tool_response": {"stderr": "gh: API rate limit exceeded for user ID 1. HTTP 403"}})
        self.assertTrue(self.hook(GUARD, {"tool_input": {"command": "gh api repos/o/r/issues/1"}}))
        self.assertIsNone(self.hook(GUARD, {"tool_input": {"command": "gh issue list"}}))

    def test_the_hold_runs_to_the_reset_the_account_reports_and_clears_itself(self):
        now = time.time()
        rates = {"rest": {"remaining": 4892, "reset": now + 3000}, "graphql": {"remaining": 0, "reset": now + 900}}
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_PROBE": "1"}):
            until = gh_budget.note_limit(resources=("graphql",), fetch=lambda: rates)
        self.assertAlmostEqual(now + 900, until, delta=5)
        self.assertEqual(0.0, gh_budget.blocked_until("rest"))
        state = json.loads((self.home / "gh-limit.json").read_text())
        state["graphql"] = time.time() - 1
        (self.home / "gh-limit.json").write_text(json.dumps(state))
        self.assertEqual("", gh_budget.refusal("graphql"))

    def test_a_queued_write_waits_for_the_reset_then_runs_once_and_is_reported(self):
        self._graphql_out()
        self.assertEqual(1, gh_budget.enqueue(["gh", "issue", "close", "783"], cwd=str(self.home)))
        calls = []
        self.assertIn("wait for the GraphQL reset", gh_budget.replay(run=lambda a, c: calls.append(a)))
        self.assertEqual([], calls)
        gh_budget.clear()
        done = subprocess.CompletedProcess([], 0, "", "")
        report = gh_budget.replay(run=lambda a, c: calls.append(a) or done)
        self.assertEqual([["gh", "issue", "close", "783"]], calls)
        self.assertIn("wrote: gh issue close 783", report)
        self.assertIn("wrote", (self.home / "gh-queue-report.txt").read_text())
        self.assertEqual("", gh_budget.replay(run=lambda a, c: done))
        from lib import cmd_ghreplay
        self.assertEqual("", cmd_ghreplay.run(), "an idle job run prints nothing")

    def test_a_failed_replay_stays_queued(self):
        gh_budget.enqueue(["gh", "issue", "close", "5"], cwd=str(self.home))
        bad = subprocess.CompletedProcess([], 1, "", "boom")
        self.assertIn("kept: gh issue close 5", gh_budget.replay(run=lambda a, c: bad))
        self.assertIn("close", (self.home / "gh-queue.jsonl").read_text())

    def test_only_gh_commands_are_queued(self):
        with self.assertRaises(ValueError):
            gh_budget.enqueue(["rm", "-rf", "x"])

    def test_the_launchd_job_runs_the_replay(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib import cmd_ghreplay
        self.assertEqual(["gh-limit", "replay"], cmd_ghreplay.plist()["ProgramArguments"][-2:])
