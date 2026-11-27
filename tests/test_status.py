"""`olivercode status`: open count, landing rate and projected zero date from gh REST, with no model call."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner, cmd_status, local_config  # noqa: E402

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)  # noon UTC is still 22 Nov in New York, so "landed today" holds for the fixture's landings (#1486)


def stage(story: str, name: str, hhmm: str, seconds: int = 0, repo: str = "r") -> dict:
    return {"story": story, "repo": repo, "stage": name, "at": f"2026-11-22T{hhmm}:00Z", "seconds": seconds}


def issue(created: str, closed: str | None = None, reason: str = "completed") -> dict:
    return {"created_at": created + "T00:00:00Z", "closed_at": closed + "T00:00:00Z" if closed else None, "state_reason": reason if closed else None}


class TestStatus(unittest.TestCase):
    def status(self, open_now, rows, slug="o/r"):
        out = io.StringIO()
        code = cmd_status.run(slug, count=lambda s, state: open_now, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"),
                              live=lambda now, count, rows: [], waiting=lambda: [])
        return code, out.getvalue()

    def test_status_names_a_story_a_policy_stop_left_waiting_on_the_owner(self):
        step = "Story #1012 waits on you: triggers.deleteFiles stopped its builder at the Owner identifiers gate, so drain did not restart it."
        out = io.StringIO()
        cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"),
                       live=lambda now, count, rows: [], waiting=lambda: [f"- #7 {step}"])
        self.assertIn("Needs you:\n- #7 " + step, out.getvalue())

    def test_the_owner_section_opens_the_page_and_says_nothing_when_no_item_waits(self):
        code, text = self.status(14, [issue("2026-11-20")] * 3)
        self.assertTrue(text.startswith("Needs you:\nNothing.\n"))
        self.assertLess(text.index("Needs you:"), text.index("Pace:"))

    def test_the_sections_follow_the_owner_then_building_then_landed_then_pace(self):
        log = [stage("story-5", "claimed", "09:00"), stage("story-5", "landed", "09:17", 120)]
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", return_value=log), mock.patch.object(cmd_status, "live_claims", return_value={}), \
                mock.patch.object(cmd_status, "runner_alive", return_value=False), mock.patch.object(cmd_status, "digest_path", return_value=Path("/none")):
            cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"), waiting=lambda: [])
        text = out.getvalue()
        order = [text.index(h) for h in ("Needs you:", "Building:", "Landed today:", "Pace:")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Landed: #5 in r at 2026-11-22 04:17 EST. Building took under a minute, validation under a minute, landing under a minute, 17 minutes in all.", text)

    def test_an_unreadable_run_log_is_named_as_unknown_and_no_figure_is_guessed(self):
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", side_effect=OSError("Permission denied")):
            code = cmd_status.run("o/r", count=lambda s, state: 2, fetch=lambda s, since: [issue("2026-11-20")], now=NOW,
                                  out=lambda t: out.write(t + "\n"), waiting=lambda: [])
        text = out.getvalue()
        self.assertEqual(0, code)
        self.assertIn("Building and landed today: unknown, because the run log could not be read (Permission denied).", text)
        self.assertIn("Tokens and sizes: unknown, because the run log could not be read (Permission denied).", text)
        self.assertNotIn("Runner idle", text)

    def test_a_falling_count_prints_the_rate_and_a_zero_date(self):
        rows = [issue("2026-11-01", "2026-11-20")] * 14 + [issue("2026-11-20")] * 7
        code, text = self.status(14, rows)
        self.assertEqual(0, code)
        self.assertIn("14 open", text)
        self.assertIn("2.0 stories landed per day", text)
        self.assertIn("reaches zero on 2026-12-06", text)

    def test_a_flat_count_says_the_date_is_not_reachable(self):
        rows = [issue("2026-11-20", "2026-11-21")] * 7
        code, text = self.status(5, rows)
        self.assertEqual(0, code)
        self.assertIn("1.0 stories landed per day", text)
        self.assertIn("not reachable at this rate", text)

    def test_a_rising_count_says_the_date_is_not_reachable(self):
        _, text = self.status(5, [issue("2026-11-20")] * 3)
        self.assertIn("not reachable at this rate", text)

    def test_issues_outside_the_window_are_not_counted(self):
        _, text = self.status(5, [issue("2026-10-01", "2026-10-02")])
        self.assertIn("0 closed as completed and 0 opened", text)

    def test_an_issue_closed_as_not_planned_is_not_counted_as_landed(self):
        rows = [issue("2026-11-01", "2026-11-20"), issue("2026-11-01", "2026-11-21", reason="not_planned")]
        _, text = self.status(5, rows)
        self.assertIn("1 closed as completed and 0 opened, so 0.1 stories landed per day.", text)

    def test_the_tokens_per_closed_story_average_the_run_log_of_the_stories_that_recorded_tokens(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=4), dict(issue("2026-11-01", "2026-11-21"), number=5), dict(issue("2026-11-01"), number=6)]
        log = [{"story": "story-4", "input": 600, "output": 400}, {"story": "story-4", "input": 1000, "output": 0},
               {"story": "story-5", "input": 1000, "output": 0}, {"story": "story-6", "input": 9000, "output": 0}]
        self.assertEqual("Tokens per closed story: 1,500 across the 2 stories that recorded tokens, out of 2 closed in the last 7 days.",
                         cmd_status.tokens_per_story(rows, log))
        self.assertIn("not recorded", cmd_status.tokens_per_story(rows, []))

    def test_status_prints_the_open_count_the_rate_the_tokens_and_the_zero_date(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=n) for n in range(1, 15)] + [issue("2026-11-20")] * 7
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", return_value=[{"story": "story-1", "input": 100, "output": 50}]), \
                mock.patch.object(cmd_status, "live_claims", return_value={}), mock.patch.object(cmd_status, "runner_alive", return_value=False):
            cmd_status.run("o/r", count=lambda s, state: 14, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"))
        text = out.getvalue()
        for want in ("14 open", "2.0 stories landed per day", "Tokens per closed story: 150", "reaches zero on 2026-12-06"):
            self.assertIn(want, text)

    def test_a_failed_read_prints_the_figures_as_unknown_and_exits_one(self):
        code, text = self.status(None, [])
        self.assertEqual(1, code)
        self.assertIn("Open count, landing rate and finish date: unknown, because the issues of o/r were not read from GitHub.", text)
        code, text = self.status(1, None)
        self.assertEqual(1, code)
        self.assertIn("Tokens per closed story: unknown, because the closed issues were not read from GitHub.", text)

    def test_no_origin_exits_one(self):
        self.assertEqual(1, self.status(1, [], slug=None)[0])

    def test_recent_leaves_out_pull_requests(self):
        class Done:
            returncode = 0
            stdout = '[[{"created_at": "a"}, {"created_at": "b", "pull_request": {}}]]'
        self.assertEqual([{"created_at": "a"}], cmd_status.recent("o/r", NOW, runner=lambda args: Done()))


class TestWaitingLines(unittest.TestCase):
    def test_waiting_lists_only_steps_whose_job_still_runs_and_closes_the_removed_ones_once(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            cmd_owner.add("maintain", "maintain health: docs failed")
            cmd_owner.add("fleet-sync", "Bring my-repo level with origin: 2 uncommitted file(s)", "git status --porcelain", "dirty")
            cmd_owner.add("s1", "Sign in to the mail host", "gh auth login", "refused")
            self.assertEqual(["- #3 Sign in to the mail host"], cmd_status.waiting_lines())
            self.assertEqual(0, cmd_owner.retire_removed())
            self.assertEqual(["- #3 Sign in to the mail host"], cmd_status.waiting_lines())


def decision(n: int, words: str = "Option A") -> dict:
    return {"created": "2026-11-22T10:00:00+00:00", "decision": f"D{n}", "thread": "T1", "words": words, "options": ["A", "B"], "choice": "A", "by": "SID"}


def round_row(n: int) -> dict:
    return {"story": f"#{n}", "round": 1, "model": "claude-haiku-5-5", "input": 1200, "output": 300, "cache_read": 0, "cache_write": 0, "cost_usd": 0.012}


class TestDigest(unittest.TestCase):
    def write(self, decisions, runs, rows=None, open_now=14, slug="o/r", opened=None, waiting=None):
        out = io.StringIO()
        target = Path(self.tmp.name) / "status-digest.md"
        code = cmd_status.digest(slug, count=lambda s, state: open_now, fetch=lambda s, since: rows or [issue("2026-11-20")] * 3, now=NOW,
                                 out=lambda t: out.write(t + "\n"), decisions=lambda: decisions, runs=lambda: runs, target=target,
                                 opened=lambda slug: opened if opened is not None else [], waiting=lambda: waiting or [])
        return code, out.getvalue(), target

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_digest_is_written_within_the_token_limit(self):
        decisions = [decision(n, words="Option A " * 60) for n in range(1000)]
        runs = [round_row(n) for n in range(1000)]
        code, text, target = self.write(decisions, runs)
        self.assertEqual(0, code)
        body = target.read_text(encoding="utf-8")
        self.assertLessEqual(cmd_status.tokens(body), cmd_status.DIGEST_TOKENS)
        self.assertIn(f"tokens, limit {cmd_status.DIGEST_TOKENS}", text)

    def test_the_newest_decisions_are_kept_when_the_digest_trims(self):
        decisions = [decision(n, words="Option A " * 60) for n in range(1000)]
        _, _, target = self.write(decisions, [])
        body = target.read_text(encoding="utf-8")
        self.assertIn("## Decisions, 5 of 1000", body)
        self.assertIn("D999", body)
        self.assertNotIn("D0:", body)

    def test_the_board_line_and_both_logs_appear(self):
        _, _, target = self.write([decision(1)], [round_row(7)])
        body = target.read_text(encoding="utf-8")
        self.assertIn("o/r: 14 open.", body)
        self.assertIn("- D1: chose A on 2026-11-22 in thread T1. Words: Option A", body)
        self.assertIn("- #7 round 1 on claude-haiku-5-5: 1200 in and 300 out tokens, cost $0.01", body)

    def test_a_review_row_names_its_findings(self):
        _, _, target = self.write([], [{"story": "#7", "review": "findings", "findings": "The gate fails on line 3."}])
        self.assertIn("- #7 review findings. Findings: The gate fails on line 3.", target.read_text(encoding="utf-8"))

    def test_the_digest_lists_open_stories_by_priority_the_last_five_landed_and_what_waits(self):
        opened = [{"number": 3, "title": "Low", "body": "Priority: P2.", "labels": []}, {"number": 9, "title": "First", "body": "Priority: P0.", "labels": []}]
        rows = [{"number": n, "title": f"Done {n}", "closed_at": f"2026-11-{10 + n}T00:00:00Z", "state_reason": "completed", "created_at": "2026-11-01T00:00:00Z"} for n in range(1, 8)]
        _, _, target = self.write([], [], rows=rows, opened=opened, waiting=["- #4 Approve the push"])
        body = target.read_text(encoding="utf-8")
        self.assertLess(body.index("P0 #9 First"), body.index("P2 #3 Low"))
        landed = body.split("## Landed, the last five\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(["- #7 Done 7 (2026-11-17)", "- #6 Done 6 (2026-11-16)", "- #5 Done 5 (2026-11-15)", "- #4 Done 4 (2026-11-14)", "- #3 Done 3 (2026-11-13)"], landed)
        self.assertIn("## Waits on the owner\n- #4 Approve the push", body)

    def test_the_session_lines_are_three_and_name_the_open_count_the_last_landing_and_the_digest(self):
        log = [stage("story-4", "claimed", "08:00"), stage("story-4", "landed", "08:10", 600), stage("story-5", "claimed", "09:00"), stage("story-5", "landed", "09:20", 1200)]
        lines = cmd_status.session_lines("o/r", 14, log, Path("/x/status-digest.md"))
        self.assertEqual(["o/r: 14 open stories.", "Last story landed: #5 in r at 2026-11-22 04:20 EST.", "Read /x/status-digest.md before acting."], lines)
        self.assertIn("No story landing is recorded", cmd_status.session_lines("o/r", 0, [], Path("/x"))[1])

    def test_no_origin_writes_nothing_and_exits_one(self):
        code, text, target = self.write([], [], slug=None)
        self.assertEqual(1, code)
        self.assertIn("no GitHub origin", text)
        self.assertFalse(target.exists())

    def test_a_failed_read_writes_nothing_and_exits_one(self):
        out = io.StringIO()
        target = Path(self.tmp.name) / "status-digest.md"
        code = cmd_status.digest("o/r", count=lambda s, state: None, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"),
                                 decisions=lambda: [], runs=lambda: [], target=target, opened=lambda slug: [], waiting=lambda: [])
        self.assertEqual(1, code)
        self.assertIn("were not read", out.getvalue())
        self.assertFalse(target.exists())

    def test_a_story_building_prints_its_stage_its_stage_time_and_its_total(self):
        """#1291: claimed at 09:35 and validating since 09:37, status at 09:40."""
        at = datetime(2026, 11, 22, 9, 40, tzinfo=timezone.utc)
        claims = {"o/shop#853": {"agent": "drain", "at": at.timestamp() - 300}}
        log = [stage("story-853", "claimed", "09:35", repo="shop"), stage("story-853", "building", "09:35", repo="shop"), stage("story-853", "validating", "09:37", 120, "shop"),
               {"story": "story-853", "round": 1, "cost_usd": 1.5, "at": "2026-11-22T09:36:00Z"}]
        lines = cmd_status.activity(at.timestamp(), claims, log, True, 5, "P0 #9 First")
        self.assertEqual(["#853 in shop: validating for 3 minutes, 5 minutes in all, $1.50 so far.", "Last landed: none recorded yet.",
                          "Next Ready: P0 #9 First."], lines)

    def test_a_story_with_no_stage_rows_counts_from_its_claim_and_never_prints_a_negative_time(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() + 90}}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], True, 1, "")
        self.assertEqual("#7 in r: claimed for under a minute, under a minute in all.", lines[0])

    def test_a_landed_story_shows_build_minutes_and_cost_validation_landing_and_total(self):
        log = [stage("story-5", "claimed", "09:00"), stage("story-5", "building", "09:00", 0), {"story": "story-5", "round": 1, "cost_usd": 2.0, "at": "2026-11-22T09:05:00Z"},
               stage("story-5", "validating", "09:12", 720), {"story": "story-5-review", "round": 1, "cost_usd": 0.5, "at": "2026-11-22T09:14:00Z"},
               stage("story-5", "landing", "09:15", 180), stage("story-5", "landed", "09:17", 120)]
        lines = cmd_status.activity(NOW.timestamp(), {}, log, False, 0, "")
        self.assertEqual("Last landed: #5 in r at 2026-11-22 04:17 EST. Building took 12 minutes and $2.50, validation 3 minutes, landing 2 minutes, 17 minutes in all.", lines[1])

    def test_the_last_landing_is_the_runners_landed_row_and_never_a_closed_issue(self):
        """#1291: an issue closed as not planned leaves no landed row, so the line names the story the runner landed."""
        log = [stage("story-3", "claimed", "08:00"), stage("story-3", "landed", "08:20", 1200), stage("story-9", "claimed", "09:00"), stage("story-9", "stopped", "09:10", 600)]
        with mock.patch.object(cmd_status, "runner_alive", return_value=False), mock.patch.object(cmd_status, "run_log", return_value=log), \
                mock.patch.object(cmd_status, "digest_path", return_value=Path(self.tmp.name) / "none.md"), mock.patch.object(cmd_status, "live_claims", return_value={}):
            lines = cmd_status.live_lines(NOW, 1)
        landed = [l for l in lines if l.startswith("Landed: ")]
        self.assertEqual(1, len(landed))
        self.assertIn("#3 in r at 2026-11-22 03:20 EST", landed[0])
        self.assertNotIn("#9", landed[0])

    def sized(self, n: int, size: str | None, retry: bool = False) -> list[dict]:
        row = stage(f"story-{n}", "claimed", "09:00")
        if size:
            row["size"] = size
        rows = [row, stage(f"story-{n}", "validating", "09:05"), {"story": f"story-{n}", "round": 1, "cost_usd": 0.10, "at": "2026-11-22T09:04:00Z"}]
        return rows + ([stage(f"story-{n}", "validating", "09:08")] if retry else []) + [stage(f"story-{n}", "landed", "09:10")]

    def test_a_size_with_five_landings_shows_its_medians_beside_the_benchmark(self):
        """#1301."""
        log = [r for n in range(5) for r in self.sized(n, "XS", retry=n == 0)]
        self.assertEqual(["XS stories: 5 reached staging in the last 7 days. Median 10.0 minutes, 1 rounds, $0.10, 80% passed validation first time. "
                          "Benchmark: 21 minutes and $0.14. Ceiling: $1.00."], cmd_status.size_lines(log, NOW.timestamp()))

    def test_a_size_without_a_ceiling_shows_none(self):
        line = cmd_status.size_lines([r for n in range(5) for r in self.sized(n, "L")], NOW.timestamp())[0]
        self.assertNotIn("Ceiling", line)

    def test_a_size_with_fewer_than_five_landings_says_it_is_too_few(self):
        log = [r for n in range(3) for r in self.sized(n, "S")]
        self.assertEqual(["S stories: 3 reached staging in the last 7 days, too few to compare."], cmd_status.size_lines(log, NOW.timestamp()))

    def test_rows_from_before_sizes_were_logged_count_as_no_size(self):
        self.assertEqual([], cmd_status.size_lines([r for n in range(6) for r in self.sized(n, None)], NOW.timestamp()))

    def test_a_landing_older_than_the_window_is_left_out(self):
        self.assertEqual([], cmd_status.size_lines([r for n in range(6) for r in self.sized(n, "XS")], NOW.timestamp() + 8 * 86400))

    def test_a_stage_row_is_not_listed_as_a_round_in_the_digest(self):
        text = cmd_status.build_digest("b", [], [stage("story-1", "claimed", "09:00")], NOW)
        self.assertNotIn("story-1", text)

    def test_an_idle_runner_says_so_and_names_the_command_that_starts_it(self):
        lines = cmd_status.activity(NOW.timestamp(), {}, [], False, 3, "")
        self.assertEqual(["Runner idle: no story is building and 3 stories are open. Start it with `olivercode drain REPO`.",
                          "Last landed: none recorded yet."], lines)

    def test_a_stalled_builder_is_warned_with_the_command_that_resumes_it(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 1, "")
        self.assertIn("the runner has stalled on #7", lines[-1])
        self.assertIn("olivercode dispatch 7", lines[-1])

    def test_a_stalled_claim_while_a_run_holds_the_repo_names_the_kill_that_releases_it_and_never_dispatch(self):
        """#1076: dispatch would only join the holding run's queue, so the warning names that run's kill instead."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 1, "", {"pid": 4242, "who": "drain r"})
        self.assertIn("#7 holds a claim by drain with no progress for 60 minutes", lines[-1])
        self.assertIn("`kill 4242`", lines[-1])
        self.assertNotIn("dispatch", lines[-1])

    def test_a_last_run_that_stopped_badly_names_no_dispatch_while_a_run_holds_the_repo(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), {}, log, True, 2, "", {"pid": 4242, "who": "drain r"})
        self.assertEqual("Warning: the last run on story-5 stopped with max_turns.", lines[-1])

    def test_a_claim_without_a_live_runner_says_it_once_in_a_plain_sentence_with_its_clear_time(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 60}}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], False, 1, "")
        self.assertEqual("#7 is claimed but nothing is building. The claim clears by itself at 08:59 EST.", lines[0])
        self.assertFalse(any(line.startswith("Warning") or "dispatch-claims" in line or "Runner idle" in line for line in lines))

    def test_a_last_run_that_did_not_stop_cleanly_is_warned_with_its_stop_reason(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), {}, log, False, 2, "")
        self.assertIn("the last run on story-5 stopped with max_turns", lines[-1])

    def test_the_run_log_skips_lines_that_are_not_objects(self):
        log = Path(self.tmp.name) / "run-log.jsonl"
        log.write_text('{"story": "#1", "round": 1}\n\nnot json\n[1, 2]\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name}):
            self.assertEqual([{"story": "#1", "round": 1}], cmd_status.run_log())

    def test_a_run_log_row_carries_the_time_it_was_written(self):
        """#987: each row says when it was written, so the status line can tell a stalled builder from a slow one."""
        from lib import agent_loop
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name}):
            agent_loop.log_round("story-7", 1, "m", {"stop": "end_turn"})
            row = cmd_status.run_log()[-1]
        self.assertRegex(row["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_missing_run_log_reads_as_empty(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name}):
            self.assertEqual([], cmd_status.run_log())


class TestRunnerAlive(unittest.TestCase):
    def test_the_process_table_is_read_with_pgrep_full_command_so_the_caller_can_see_itself(self):
        with mock.patch.object(cmd_status.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(cmd_status.runner_alive())
        self.assertEqual(["pgrep", "-fa", "olivercode (drain|dispatch)"], run.call_args.args[0])

    def test_no_drain_or_dispatch_process_reads_as_not_alive(self):
        with mock.patch.object(cmd_status.subprocess, "run", return_value=mock.Mock(returncode=1)):
            self.assertFalse(cmd_status.runner_alive())

    def test_a_missing_pgrep_reads_as_not_alive(self):
        with mock.patch.object(cmd_status.subprocess, "run", side_effect=OSError):
            self.assertFalse(cmd_status.runner_alive())


class TestOwnerZone(unittest.TestCase):
    """#1486: every time status and watch print is in the owner's zone, watch opens with the current state, and Next Ready skips a claimed story."""

    def test_a_stage_line_is_stamped_with_its_row_time_in_the_owners_zone(self):
        row = stage("story-1395", "validating", "19:40", repo="oc-staging")
        self.assertEqual("14:40 EST #1395 in oc-staging: validating", cmd_status.watch_line(row, []))

    def test_timezone_local_prints_this_computers_zone(self):
        row = stage("story-1395", "validating", "19:40", repo="oc-staging")
        with mock.patch.object(local_config, "setting", return_value="local"), mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            time.tzset()
            try:
                line = cmd_status.watch_line(row, [])
            finally:
                os.environ.pop("TZ", None)
                time.tzset()
        self.assertEqual("04:40 JST #1395 in oc-staging: validating", line)

    def test_landed_today_is_the_owners_local_date(self):
        log = [stage("story-1", "claimed", "02:00"), stage("story-1", "landed", "03:00", 60),
               stage("story-2", "claimed", "09:00"), stage("story-2", "landed", "10:00", 60)]
        self.assertEqual(["story-2"], [f["story"] for f in cmd_status.landed_today(log, NOW.timestamp())])

    def test_next_ready_names_the_first_open_story_with_no_live_claim(self):
        digest = "# Status digest\nWritten 2026-11-22 12:00 UTC.\n\n## Open, 2 in priority order\n- P0 #1479 Staging CI passes again\n- P1 #1289 Next story\n\n## Landed\n- none\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "status-digest.md"
            path.write_text(digest, encoding="utf-8")
            self.assertEqual("P0 #1479 Staging CI passes again", cmd_status.next_ready(path))
            self.assertEqual("P1 #1289 Next story", cmd_status.next_ready(path, {"o/r#1479": {"agent": "drain", "at": 0}}))

    def test_watch_opens_with_the_building_block_the_landings_and_next_ready_then_streams(self):
        log = [stage("story-7", "claimed", "09:00"), stage("story-5", "claimed", "08:00"), stage("story-5", "landed", "09:17", 120)]
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 120}}
        lines = []
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "status-digest.md"
            path.write_text("# Status digest\n\n## Open, 2 in priority order\n- P0 #7 Building story\n- P1 #9 First\n\n## Landed\n- none\n", encoding="utf-8")
            with mock.patch.object(cmd_status, "run_log", return_value=log), mock.patch.object(cmd_status, "live_claims", return_value=claims), \
                    mock.patch.object(cmd_status, "digest_path", return_value=path):
                code = cmd_status.command_watch([], sleep=lambda s: None, out=lines.append, alive=lambda: False)
        self.assertEqual(0, code)
        self.assertTrue(lines[0].startswith("#7 is claimed but nothing is building. The claim clears by itself at "))
        self.assertTrue(lines[1].startswith("Last landed: #5 in r at 2026-11-22 04:17 EST. Building took"))
        self.assertEqual("Next Ready: P1 #9 First.", lines[2])
        self.assertEqual("No drain is running.", lines[-1])


if __name__ == "__main__":
    unittest.main()
