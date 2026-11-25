"""`olivercode status`: open count, landing rate and projected zero date from gh REST, with no model call."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import agent_loop, cmd_drain, status_report  # noqa: E402
from _support import quiet  # noqa: E402
from test_drain import FakeIo, issue as drain_issue, state as drain_state  # noqa: E402
from lib import cmd_boardsweep as sweep  # noqa: E402
from lib import cmd_fleetsync, cmd_groom, cmd_install, cmd_owner, cmd_status, status_page  # noqa: E402

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def issue(created: str, closed: str | None = None) -> dict:
    return {"created_at": created + "T00:00:00Z", "closed_at": closed + "T00:00:00Z" if closed else None}


class TestStatus(unittest.TestCase):
    def status(self, open_now, rows, slug="o/r"):
        out = io.StringIO()
        code = cmd_status.run(slug, count=lambda s, state: open_now, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"),
                              live=lambda now, count, rows: [], waiting=lambda: [], cands=lambda: "")
        return code, out.getvalue()

    def test_status_warning_names_the_last_api_error_cause(self):
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp(), "at": NOW.timestamp()}}
        notes = cmd_status.story_notes(NOW.timestamp(), claims, [{"story": "story-7", "stop": "api_error", "error": "rate limit exceeded"}], True, None, {})
        self.assertIn("rate limit exceeded", notes["7"])

    def test_status_names_a_story_a_policy_stop_left_waiting_on_the_owner(self):
        step = "Story #1012 waits on you: triggers.gateFailures stopped its builder at the Owner identifiers gate, so drain did not restart it."
        out = io.StringIO()
        cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"),
                       live=lambda now, count, rows: [], waiting=lambda: [f"- #7 {step}"], cands=lambda: "")
        self.assertIn("Waits on the owner:\n- #7 " + step, out.getvalue())

    def test_status_names_the_candidates_waiting(self):
        out = io.StringIO()
        cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"),
                       live=lambda now, count, rows: [], waiting=lambda: [], cands=lambda: "- 3 candidate(s) wait: run `olivercode candidates` to review them.")
        self.assertIn("3 candidate(s) wait: run `olivercode candidates`", out.getvalue())

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
        self.assertIn("0 closed and 0 opened", text)

    def test_tokens_per_closed_story_include_cache_review_and_cost(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=4), dict(issue("2026-11-01", "2026-11-21"), number=5), dict(issue("2026-11-01"), number=6)]
        log = [
            {"story": "story-4", "input": 600, "output": 400, "cache_read": 1000, "cache_write": 100, "cost_usd": 1.25},
            {"story": "story-4-review", "input": 100, "output": 50, "cache_read": 200, "cache_write": 50, "cost_usd": 0.25},
            {"story": "story-5", "input": 500, "output": 100, "cache_read": 300, "cache_write": 100, "cost_usd": 1.00},
            {"story": "story-6", "input": 9000, "output": 0, "cost_usd": 9.00},
        ]
        self.assertEqual("Tokens per closed story: 1,750 across 2 stories closed in the last 7 days, average cost $1.25.", cmd_status.tokens_per_story(rows, log))
        self.assertIn("not recorded", cmd_status.tokens_per_story(rows, []))

    def test_status_page_numbers_show_average_cost_per_closed_story(self):
        html = status_page.numbers_block({"tokens_per_closed": 1234, "cost_per_closed": 2.5, "handovers": 1, "threads": 2, "open": 3})
        self.assertIn("Tokens per closed story", html)
        self.assertIn("Average cost per closed story", html)
        self.assertIn("$2.50", html)

    def test_status_prints_the_open_count_the_rate_the_tokens_and_the_zero_date(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=n) for n in range(1, 15)] + [issue("2026-11-20")] * 7
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", return_value=[{"story": "story-1", "input": 100, "output": 50}]), \
                mock.patch.object(cmd_status, "live_claims", return_value={}), mock.patch.object(cmd_status, "runner_alive", return_value=False):
            cmd_status.run("o/r", count=lambda s, state: 14, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"))
        text = out.getvalue()
        for want in ("14 open", "2.0 stories landed per day", "Tokens per closed story: 150", "reaches zero on 2026-12-06"):
            self.assertIn(want, text)

    def test_a_failed_read_exits_one(self):
        code, text = self.status(None, [])
        self.assertEqual(1, code)
        self.assertIn("were not read", text)

    def test_no_origin_exits_one(self):
        self.assertEqual(1, self.status(1, [], slug=None)[0])

    def test_no_origin_names_the_folder_and_where_to_go(self):
        out = io.StringIO()
        code = cmd_status.run(None, out=lambda t: out.write(t + "\n"), folder=Path("/x/notes"))
        self.assertEqual(1, code)
        self.assertIn("/x/notes is not a repo with a GitHub origin", out.getvalue())
        self.assertIn("cd into a repo with a GitHub origin", out.getvalue())
        self.assertIn("OliverCode checkout", out.getvalue())

    def test_recent_leaves_out_pull_requests(self):
        class Done:
            returncode = 0
            stdout = '[[{"created_at": "a"}, {"created_at": "b", "pull_request": {}}]]'
        self.assertEqual([{"created_at": "a"}], cmd_status.recent("o/r", NOW, runner=lambda args: Done()))


class TestStatusLayout(unittest.TestCase):
    """#1117: status opens with the figures, then sections set off by blank lines, one line for each building story, and no story line over 80 columns."""

    def test_minutes_count_from_the_claims_start_and_a_renewal_does_not_reset_them(self):
        """#1093: a claim renewed every minute kept reading 0 or -1 minutes (#1122)."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 26 * 60, "at": NOW.timestamp() + 5}}
        log = [{"story": "story-7", "round": 1}, {"story": "story-7"}]
        self.assertEqual("r #7 · Building · claimed 26m, activity 26m, 1 round", cmd_status.state_lines(NOW.timestamp(), claims, log, {}, None, [], 1, "", [], "o/r")[0])

    def test_minutes_count_from_the_start_when_the_claim_was_rewritten_a_minute_ago(self):
        """#1086: a claim posted again keeps its start, so 42 minutes of building read 42 minutes (#1122)."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 42 * 60, "at": NOW.timestamp() - 60}}
        self.assertEqual("r #7 · Building · claimed 42m, activity 42m, 0 rounds", cmd_status.state_lines(NOW.timestamp(), claims, [], {}, None, [], 1, "", [], "o/r")[0])

    def test_three_building_stories_print_one_line_each_under_blank_separated_sections_in_80_columns(self):
        claims = {f"o/OliverCode#{n}": {"agent": "drain", "since": NOW.timestamp() - 42 * 60, "at": NOW.timestamp()} for n in (1105, 1107, 996)}
        log = [{"story": "story-1105", "review": "pass", "at": "2026-11-21T23:50:00Z"}]
        issues = [{"number": 1105, "body": "Size: S"}, {"number": 1107, "body": "Size: M"}, {"number": 996, "body": "Size: M"}]
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", return_value=log), mock.patch.object(cmd_status, "live_claims", return_value=claims), \
                mock.patch.object(cmd_status, "runner_alive", return_value=True), mock.patch.object(cmd_status.run_lock, "active", return_value=None), \
                mock.patch.object(cmd_status.run_lock, "holders_elsewhere", return_value=[]), mock.patch.object(cmd_status, "next_ready", return_value=""), \
                mock.patch.object(cmd_status, "held_numbers", return_value=set()), mock.patch.object(cmd_status, "closed_claims", return_value=set()), \
                mock.patch.object(cmd_status.open_issues, "fetch", return_value=issues), mock.patch.object(cmd_status, "last_commit", return_value=None), \
                mock.patch.object(cmd_status, "validation_slots", return_value=([], 1)), mock.patch.object(cmd_status.gh_budget, "refusal", return_value=""), \
                mock.patch("lib.gated.savings_lines", return_value=[]):
            cmd_status.run("o/OliverCode", count=lambda s, state: 3, fetch=lambda s, since: [], now=NOW, out=lambda t: out.write(t + "\n"),
                           waiting=lambda: [], cands=lambda: "", numbers=lambda: {"tokens_per_closed": None, "handovers": 0, "threads": 0, "open": 3})
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("o/OliverCode: 3 open."))
        self.assertEqual("", lines[1])
        self.assertEqual("", lines[lines.index("Building:") - 1])
        self.assertIn("OliverCode #1105 · S · Landing · claimed 42m, activity 10m, 0 rounds", lines)
        self.assertIn("OliverCode #1107 · M · Building · claimed 42m, activity 42m, 0 rounds", lines)
        story_lines = [line for line in lines if " · " in line]
        self.assertEqual(3, len(story_lines))
        self.assertTrue(all(len(line) <= 80 for line in story_lines))
        self.assertEqual(1, sum("#1105" in line for line in lines))


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
                                 opened=lambda slug: opened if opened is not None else [], waiting=lambda: waiting or [], cands=lambda: "")
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
        rows = [{"number": n, "title": f"Done {n}", "closed_at": f"2026-11-{10 + n}T00:00:00Z", "created_at": "2026-11-01T00:00:00Z"} for n in range(1, 8)]
        _, _, target = self.write([], [], rows=rows, opened=opened, waiting=["- #4 Approve the push"])
        body = target.read_text(encoding="utf-8")
        self.assertLess(body.index("P0 #9 First"), body.index("P2 #3 Low"))
        landed = body.split("## Landed, the last five\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(["- #7 Done 7 (2026-11-17)", "- #6 Done 6 (2026-11-16)", "- #5 Done 5 (2026-11-15)", "- #4 Done 4 (2026-11-14)", "- #3 Done 3 (2026-11-13)"], landed)
        self.assertIn("## Waits on the owner\n- #4 Approve the push", body)

    def test_next_ready_passes_over_a_claimed_story_and_an_owner_gated_one(self):
        """#1020: Next Ready names the first open story that is neither claimed nor waiting on the owner."""
        opened = [{"number": 1, "title": "Gated", "body": "Priority: P0.", "labels": [{"name": "owner-action"}]},
                  {"number": 2, "title": "Claimed", "body": "Priority: P1.", "labels": []},
                  {"number": 3, "title": "Ready", "body": "Priority: P2.", "labels": []}]
        _, _, target = self.write([], [], opened=opened)
        self.assertEqual("P2 #3 Ready", cmd_status.next_ready(target, {2}))
        self.assertEqual("P1 #2 Claimed", cmd_status.next_ready(target))

    def test_held_numbers_takes_the_live_claims_and_the_open_owner_steps(self):
        """#1020: a live claim and an open owner-queue step each hold their story back from Ready; a closed step does not."""
        steps = [{"status": "open", "step": "Story #3 needs the owner's approval"}, {"status": "done", "step": "Story #4 was approved"}]
        with mock.patch.object(cmd_status, "live_claims", return_value={"o/r#2": {"agent": "drain"}}), \
                mock.patch.object(cmd_status.cmd_owner, "items", return_value=steps):
            self.assertEqual({2, 3}, cmd_status.held_numbers(NOW.timestamp()))

    def test_the_session_lines_are_three_and_name_the_open_count_the_last_landing_and_the_digest(self):
        rows = [{"number": 5, "title": "Newest", "closed_at": "2026-11-20T00:00:00Z"}, {"number": 4, "title": "Older", "closed_at": "2026-11-19T00:00:00Z"}]
        lines = cmd_status.session_lines("o/r", 14, rows, Path("/x/status-digest.md"))
        self.assertEqual(["o/r: 14 open stories.", "Last story landed: #5 Newest.", "Read /x/status-digest.md before acting."], lines)
        self.assertIn("No story landed", cmd_status.session_lines("o/r", 0, [], Path("/x"))[1])

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

    def test_a_building_story_is_one_line_and_its_warning_sits_on_an_indented_line_under_it(self):
        t = NOW.timestamp()
        claims = {"o/r#7": {"agent": "drain", "at": t - 600}}
        lines = cmd_status.state_lines(t, claims, [], {}, None, [], 1, "", [], "o/r", cmd_status.story_notes(t, claims, [], False, None, None))
        self.assertEqual("r #7 · Building · claimed 10m, activity 10m, 0 rounds", lines[0])
        self.assertTrue(lines[1].startswith("  Warning: #7 holds a claim by drain but no drain or dispatch process is running."))

    def test_a_story_whose_log_and_commits_have_not_moved_says_so(self):
        """#1086: 45 minutes in with nothing new for 20 minutes, the warning says so with the last thing it did, and a newer commit counts as a move."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 45 * 60, "at": NOW.timestamp()}}
        log = [{"story": "story-7", "round": 1, "stop": "end_turn", "at": "2026-11-21T23:40:00Z"}]
        self.assertIn("Warning: No progress for 20 minutes: the last thing it did was ending round 1 at", cmd_status.story_notes(NOW.timestamp(), claims, log, True, None, None)["7"])
        self.assertEqual({}, cmd_status.story_notes(NOW.timestamp(), claims, log, True, None, {"7": NOW.timestamp() - 120}))

    def test_an_idle_runner_says_so_and_names_the_command_that_starts_it(self):
        self.assertEqual("Runner idle: no story is building and 3 stories are open. Start it with `olivercode drain REPO`.", cmd_status.idle_line(False, 3))
        self.assertEqual(["Last landed: none in the last 7 days."], cmd_status.last_lines(False, None, "", [], None))

    def test_a_stalled_builder_is_warned_with_the_command_that_resumes_it(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        note = cmd_status.story_notes(NOW.timestamp(), claims, log, True, None, None)["7"]
        self.assertIn("the runner has stalled on #7", note)
        self.assertIn("olivercode dispatch 7", note)

    def test_a_stalled_claim_while_a_run_holds_the_repo_names_the_kill_that_releases_it_and_never_dispatch(self):
        """#1076: dispatch would only join the holding run's queue, so the warning names that run's kill instead."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        note = cmd_status.story_notes(NOW.timestamp(), claims, log, True, {"pid": 4242, "who": "drain r"}, None)["7"]
        self.assertIn("#7 holds a claim by drain with no progress for 60 minutes", note)
        self.assertIn("`kill 4242`", note)
        self.assertNotIn("dispatch", note)

    def test_a_last_run_that_stopped_badly_names_no_dispatch_while_a_run_holds_the_repo(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        lines = cmd_status.last_lines(True, None, "", log, {"pid": 4242, "who": "drain r"})
        self.assertEqual("  Warning: the last run on story-5 stopped with max_turns.", lines[-1])

    def test_a_long_round_whose_runner_beat_a_minute_ago_is_not_stalled(self):
        """#1020: a claim 40 minutes old is building, not stalled, when the live holder is building it and its heartbeat is a minute old."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 2400}}
        holder = {"pid": 4242, "who": "drain r", "building": [7], "beat": NOW.timestamp() - 60}
        self.assertNotIn("stalled", cmd_status.story_notes(NOW.timestamp(), claims, [], True, holder, None).get("7", ""))

    def test_a_long_round_whose_holder_is_not_building_it_is_stalled(self):
        """#1020: a live holder that is building another story does not keep a stalled claim from warning."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 2400}}
        holder = {"pid": 4242, "who": "drain r", "building": [8], "beat": NOW.timestamp() - 60}
        self.assertTrue(cmd_status.story_notes(NOW.timestamp(), claims, [], True, holder, None)["7"].startswith("Warning: #7 holds a claim"))

    def test_a_claim_without_a_live_runner_names_the_stale_claim_and_its_release(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 60}}
        self.assertIn("#7 holds a claim by drain but no drain or dispatch process is running", cmd_status.story_notes(NOW.timestamp(), claims, [], False, None, None)["7"])

    def test_a_last_run_that_did_not_stop_cleanly_is_warned_with_its_stop_reason(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        self.assertIn("the last run on story-5 stopped with max_turns", cmd_status.last_lines(False, None, "", log, None)[-1])


    def test_each_building_story_names_its_repo_size_state_minutes_and_what_holds_it(self):
        """#1112: a story waiting for validation names the slot's holder, and each other state reads from the run log, the holds and the queue (#1122)."""
        t = NOW.timestamp()
        done = {"story": "story-1083", "round": 1, "at": "2026-11-21T23:56:00Z"}
        claims = {"o/OliverCode#1083": {"at": t - 900}}
        issues = {"1083": {"body": "Size: M"}}
        line = lambda **kw: cmd_status.state_lines(t, claims, kw.get("log", [done]), issues, kw.get("holder"), kw.get("slots", ["OliverCode-1084"]), 1,
                                                   kw.get("github", ""), kw.get("elsewhere", []), "o/OliverCode")
        self.assertEqual(["OliverCode #1083 · M · Waiting for validation · claimed 15m, activity 4m, 1 round · held by OliverCode #1084"], line())
        self.assertEqual(["OliverCode #1083 · M · Validating · claimed 15m, activity 4m, 1 round"], line(slots=["OliverCode-1083"]))
        self.assertEqual(["OliverCode #1083 · M · Landing · claimed 15m, activity 4m, 1 round"], line(log=[{**done, "review": "pass"}]))
        self.assertEqual(["OliverCode #1083 · M · Building · claimed 15m, activity 15m, 0 rounds"], line(log=[], slots=[]))
        self.assertEqual(["OliverCode #1083 · M · Waiting for GitHub · claimed 15m, activity 15m, 0 rounds · the GraphQL rate limit"], line(log=[], github="held"))
        self.assertEqual(["OliverCode #1083 · M · Waiting for another repo · claimed 15m, activity 15m, 0 rounds · digioperator holds it"],
                         line(log=[], holder={"building": [5]}, elsewhere=["o/digioperator"]))
        both = {**claims, "o/digioperator#824": {"at": t - 900}}
        self.assertEqual(["OliverCode #1083 · M · Building · claimed 15m, activity 15m, 0 rounds", "digioperator #824 · Building · claimed 15m, activity 15m, 0 rounds"],
                         cmd_status.state_lines(t, both, [], issues, {"building": [1083]}, [], 1, "", ["o/digioperator"], "o/OliverCode"))

    def test_status_names_a_graphql_hold_as_waiting_for_github(self):
        """#1112: run() stops on a REST hold, so the live lines read GraphQL's hold, the one the runner's board calls wait on."""
        with mock.patch.object(cmd_status, "runner_alive", return_value=True), mock.patch.object(cmd_status.gh_budget, "refusal", side_effect=lambda r="": "held" if r == "graphql" else ""), \
                mock.patch.object(cmd_status, "state_lines", return_value=[]) as lines, mock.patch.object(cmd_status, "live_claims", return_value={}), \
                mock.patch.object(cmd_status, "run_log", return_value=[]):
            cmd_status.live_lines(NOW, 0, [], "")
        self.assertEqual("held", lines.call_args.args[7])

    def test_builders_from_two_repos_each_name_their_repo_and_a_closed_story_is_dropped(self):
        """#1095: a claim's repo shows on its line, a claim for another repo's number holds nothing here, and a closed story is stale, not building (#1122)."""
        claims = {"o/OliverCode#1031": {"agent": "drain", "at": NOW.timestamp() - 60}, "o/digioperator#824": {"agent": "drain", "at": NOW.timestamp() - 60}}
        lines = cmd_status.state_lines(NOW.timestamp(), claims, [], {}, None, [], 1, "", [], "o/OliverCode")
        self.assertEqual(["OliverCode #1031 · Building · claimed 1m, activity 1m, 0 rounds", "digioperator #824 · Building · claimed 1m, activity 1m, 0 rounds"], lines)
        rows = [{"number": 824, "state": "closed"}]
        gone = SimpleNamespace(returncode=0, stdout="open\n")
        self.assertEqual({"o/OliverCode#824"}, cmd_status.closed_claims({"o/OliverCode#824": {}, "o/digioperator#824": {}}, "o/OliverCode", rows, lambda a: gone))
        with mock.patch.object(cmd_status, "live_claims", return_value={"o/digioperator#824": {}}), mock.patch.object(cmd_status.cmd_owner, "items", return_value=[]):
            self.assertEqual(set(), cmd_status.held_numbers(NOW.timestamp(), "o/OliverCode"))

    def test_a_failed_read_of_another_repos_story_leaves_its_claim_building(self):
        """#1095: a gh timeout or a missing gh binary must not crash status."""
        def broken(args):
            raise OSError("no gh")
        self.assertEqual(set(), cmd_status.closed_claims({"o/other#5": {}}, "o/OliverCode", [], broken))

















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


DAY = 86400.0
T0 = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc).timestamp()


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestStatusPage(unittest.TestCase):
    """#990: the page the runner rewrites with no model call, and the one small-model call that publishes it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.published = []

    def record(self, kind, issue=None, now=T0, **kw):
        return status_report.record("o/r", kind, issue, now=now, publisher=lambda **k: self.published.append(kind), **kw)

    def page(self):
        return status_report.page_path().read_text(encoding="utf-8")

    def story(self, n, title="Story"):
        return {"number": n, "title": f"{title} {n}", "labels": []}

    def landed_log(self, n, minutes=20.0, at=T0 - 3600, origin="olivercode drain r", repo="o/r"):
        return [{"story": f"story-{n}", "round": 1, "model": "haiku", "input": 1000, "output": 500, "cost_usd": 0.25, "repo": repo, "at": stamp(at - 600)},
                {"story": f"story-{n}", "repo": repo, "landed": True, "title": f"Landed {n}", "origin": origin, "model": "haiku", "minutes": minutes, "at": stamp(at)}]

    def test_a_run_begins_with_the_estimate_the_builders_the_path_and_the_refresh_interval(self):
        log = self.landed_log(1, minutes=20.0)
        with mock.patch.object(status_report, "_log", return_value=log):
            message = self.record("begin", origin="olivercode drain r", builders=2, queue=[self.story(5), self.story(6), self.story(7), self.story(8)], log=log)
        self.assertIn("about 40 minutes for 4 stories", message)
        self.assertIn("2 builders running", message)
        self.assertIn(str(status_report.page_path()), message)
        self.assertIn(f"reloads every {status_report.REFRESH_SECONDS} seconds", message)
        self.assertIn('title this thread "r, 4 building" in the same turn', message)

    def test_a_page_written_for_a_publish_carries_the_publish_time_and_a_tick_keeps_the_last(self):
        with mock.patch.object(status_report, "_log", return_value=[]), mock.patch.object(status_report, "load_local", return_value={"cityArtifact": "u"}):
            self.record("start", self.story(5), now=T0, log=[])
            self.assertIn(f'data-published="{T0:.0f}"', self.page())
            self.record("tick", now=T0 + 3600, log=[{"story": "city-publish", "at": stamp(T0)}])  # the publish logs its own row, which a tick reads
            self.assertIn(f'data-published="{T0:.0f}"', self.page())

    def test_a_dispatch_refused_before_it_starts_fires_no_end_event(self):
        from lib import cmd_dispatch
        events = []
        io = SimpleNamespace(event=lambda kind, issue=None, **k: events.append(kind) or "")
        with mock.patch.object(cmd_dispatch, "_start_checks", return_value=1), mock.patch.object(cmd_drain, "take_run", return_value=True), \
                mock.patch.object(cmd_dispatch.run_lock, "Heartbeat"), mock.patch.object(cmd_dispatch.run_lock, "release", return_value=[]), \
                mock.patch.object(cmd_dispatch, "read_story", return_value=({"number": 5, "title": "S", "state": "OPEN", "labels": []}, "")):
            try:
                cmd_dispatch.command_dispatch(["5"], runner=lambda *a, **k: "", io=io, repo=Path(self.tmp.name))
            except Exception:
                pass
        self.assertNotIn("end", events)

    def test_a_run_with_no_landed_story_says_there_is_no_estimate_yet(self):
        with mock.patch.object(status_report, "_log", return_value=[]):
            message = self.record("begin", origin="o", queue=[self.story(5)], log=[])
        self.assertIn("Estimate: none yet", message)

    def test_the_page_shows_what_is_building_the_queue_and_what_waits_on_the_owner(self):
        with mock.patch.object(status_report, "_log", return_value=[]), mock.patch.object(status_report, "_owner_steps", return_value=[{"id": 3, "step": "Pin the City tab"}]):
            self.record("begin", origin="olivercode drain r", builders=2, queue=[self.story(5), self.story(6)], waiting=[self.story(9, "Owner gated")], log=[])
            self.record("start", self.story(5), now=T0 + 60, model_name="sonnet", queue=[self.story(6)], waiting=[self.story(9, "Owner gated")], log=[])
            text = self.page()
        self.assertIn("1 of 2 builders running", text)
        self.assertIn("#5 Story 5", text)
        self.assertIn("sonnet", text)
        self.assertIn("#6 Story 6", text)
        self.assertIn("#9 Owner gated 9", text)
        self.assertIn("Pin the City tab", text)
        self.assertIn('http-equiv="refresh"', text)
        self.assertNotIn("<img", text)

    def test_a_landing_is_logged_with_its_origin_and_shows_under_its_day_with_tokens_and_cost(self):
        rows = []
        with mock.patch.object(status_report, "_log", side_effect=lambda: list(rows)):
            self.record("begin", origin="thread SID1", queue=[self.story(5)])
            self.record("start", self.story(5), now=T0 + 10, model_name="haiku")
            agent_loop.append_log({"story": "story-5", "round": 1, "model": "haiku", "input": 4000, "output": 1000, "cost_usd": 0.5, "repo": "o/r", "at": stamp(T0 + 5)})
            self.record("land", self.story(5), now=T0 + 20 * 60 + 10)
            rows.extend(cmd_status.run_log())
            self.record("tick", now=T0 + 21 * 60)
        text = self.page()
        landing = [r for r in rows if r.get("landed")][0]
        self.assertEqual(("thread SID1", 20.0), (landing["origin"], landing["minutes"]))
        for want in ("#5 Story 5", "thread SID1", "5,000", "$0.50", "1 landed"):
            self.assertIn(want, text)

    def test_the_page_lists_seven_days_with_a_total_for_each_and_leaves_out_older_landings(self):
        log = self.landed_log(1, at=T0 - 60) + self.landed_log(2, at=T0 - 3 * DAY) + self.landed_log(3, at=T0 - 9 * DAY)
        text = status_report.render({"o/r": self._entry()}, log, T0)
        self.assertEqual(7, text.count("<h4>"))
        self.assertIn("Landed 1", text)
        self.assertIn("Landed 2", text)
        self.assertNotIn("Landed 3", text)
        self.assertIn("nothing landed", text)

    def test_a_repo_filter_keeps_another_repos_landings_off_the_page(self):
        log = self.landed_log(1, at=T0 - 60, repo="o/other")
        self.assertNotIn("Landed 1", status_report.render({"o/r": self._entry()}, log, T0))

    def _entry(self, **kw):
        return {"origin": "x", "builders": 1, "started": T0, "estimate_min": 30, "active": True, "building": {}, "queue": [], "held": [], "waiting": [], **kw}

    def test_the_clock_runs_in_the_page_and_a_stale_publish_is_warned_in_the_browser(self):
        entry = self._entry(building={"5": {"n": 5, "title": "T", "at": T0 - 600, "model": "haiku"}})
        text = status_report.render({"o/r": entry}, [], T0, published=T0 - 3600)
        self.assertIn(f'data-since="{T0 - 600:.0f}"', text)
        self.assertIn(f'data-left="{T0 + 1800:.0f}"', text)
        self.assertIn(f'data-published="{T0 - 3600:.0f}"', text)
        self.assertIn('data-active="1"', text)
        self.assertIn("Warning: this is older than", text)

    def test_the_page_follows_the_designs_colors_from_the_owners_design_file(self):
        own = Path(self.tmp.name) / "mine.md"
        own.write_text(":root { --bg: #fafaf0; --accent: #aa0000; }", encoding="utf-8")
        with mock.patch.object(status_report, "load_local", return_value={"designFile": str(own)}):
            tokens = status_report.design_tokens()
        self.assertEqual(("#fafaf0", "#aa0000", "#000000"), (tokens["bg"], tokens["accent"], tokens["text"]))
        self.assertEqual("#ffffff", status_report.design_tokens()["bg"])

    def test_a_tick_rewrites_the_page_and_publishes_nothing_while_an_event_publishes(self):
        with mock.patch.object(status_report, "_log", return_value=[]):
            self.record("begin", origin="o", queue=[self.story(5)], log=[])
            self.record("tick", now=T0 + 1800, log=[])
            self.record("end", now=T0 + 3600, log=[])
        self.assertEqual(["begin", "end"], self.published)
        self.assertIn("The run has ended", self.page())

    def test_a_held_story_shows_as_held_and_is_not_logged_as_landed(self):
        rows = []
        with mock.patch.object(status_report, "_log", side_effect=lambda: list(rows)):
            self.record("begin", origin="o", queue=[self.story(5)])
            self.record("start", self.story(5), now=T0 + 1)
            self.record("held", self.story(5), now=T0 + 60)
        self.assertEqual([], [r for r in cmd_status.run_log() if r.get("landed")])
        self.assertIn("#5 Story 5", self.page())
        self.assertIn("No story is building", self.page())

    def test_publish_does_nothing_without_a_city_url(self):
        with mock.patch.object(status_report, "load_local", return_value={}):
            self.assertFalse(status_report.publish()["ok"])
        self.assertEqual([], cmd_status.run_log())

    def test_a_publish_runs_on_the_smallest_model_and_logs_its_tokens_and_cost(self):
        calls = []

        def run(prompt, cwd, **kw):
            calls.append((prompt, kw))
            return {"code": 0, "text": "done", "usage": {"input": 900, "output": 40}, "cost_usd": 0.003}
        with mock.patch.object(status_report, "load_local", return_value={"cityArtifact": "https://claude.ai/artifact/abc"}):
            found = status_report.publish(run=run)
        self.assertTrue(found["ok"])
        self.assertEqual("haiku", calls[0][1]["model"])
        self.assertIn("https://claude.ai/artifact/abc", calls[0][0])
        row = cmd_status.run_log()[-1]
        self.assertEqual(("city-publish", 900, 40, 0.003), (row["story"], row["input"], row["output"], row["cost_usd"]))
        text = status_report.render({}, cmd_status.run_log(), datetime.now().timestamp())
        self.assertIn("940 tokens", text)

    def test_a_publish_that_fails_headless_is_recorded_stops_further_calls_and_queues_the_finding(self):
        calls = []

        def run(prompt, cwd, **kw):
            calls.append(1)
            return {"code": 1, "text": "Artifact tool is not available", "usage": {}, "cost_usd": None}
        with mock.patch.object(status_report, "load_local", return_value={"cityArtifact": "https://claude.ai/artifact/abc"}), \
                mock.patch.object(status_report.cmd_owner, "add") as add:
            first = status_report.publish(run=run)
            second = status_report.publish(run=run)
            probe = status_report.publish(run=run, probe=True)
        self.assertFalse(first["ok"])
        self.assertIn("earlier publish failed", second["detail"])
        self.assertEqual(2, len(calls))
        self.assertFalse(probe["ok"])
        self.assertIn("Artifact tool is not available", add.call_args.kwargs["error"])

    def test_the_publish_command_reports_whether_the_tool_works_with_tokens_and_cost(self):
        out = []
        ok = lambda prompt, cwd, **kw: {"code": 0, "text": "done", "usage": {"input": 800, "output": 20}, "cost_usd": 0.002}  # noqa: E731
        with mock.patch.object(status_report, "load_local", return_value={"cityArtifact": "u"}):
            self.assertEqual(0, cmd_status.publish(["--probe"], out=out.append, run=ok))
        self.assertIn("works headless. One publish cost 820 tokens and $0.0020", out[0])
        self.assertEqual(1, cmd_status.publish(["--nope"], out=out.append))

    def test_concurrent_events_each_keep_their_change_to_the_run_state(self):
        with mock.patch.object(status_report, "_log", return_value=[]):
            self.record("begin", origin="olivercode drain r", queue=[])
            threads = [threading.Thread(target=self.record, args=("start", self.story(n)), kwargs={"now": T0 + n}) for n in range(1, 13)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(12, len(status_report.load_state()["o/r"]["building"]))

    def test_a_publisher_that_raises_never_stops_the_event(self):
        def boom(**kw):
            raise TimeoutError("slow")
        with mock.patch.object(status_report, "_log", return_value=[]):
            status_report.record("o/r", "start", self.story(5), now=T0, publisher=boom)
        self.assertIn("#5 Story 5", self.page())

    def test_a_refused_close_fires_the_held_event(self):
        events = []

        class Io(FakeIo):
            def event(self, kind, issue=None, **info):
                events.append(kind)
                return ""
        io = Io([drain_issue(1)], cap=1)
        with mock.patch.object(cmd_drain, "_work_story", side_effect=cmd_drain.CloseRefused("no")):
            cmd_drain.work_story(io, drain_issue(1), drain_state())
        self.assertEqual(["held"], events)

    def test_a_story_blocked_by_a_commit_gate_fires_the_held_event(self):
        events = []

        class Io(FakeIo):
            def event(self, kind, issue=None, **info):
                events.append(kind)
                return ""
        io = Io([drain_issue(1)], cap=1)
        io.backlog = lambda n: None
        with mock.patch.object(cmd_drain, "_work_story", side_effect=cmd_drain.CommitBlocked(0)):
            cmd_drain.work_story(io, drain_issue(1), drain_state())
        self.assertEqual(["held"], events)

    def test_a_plain_publish_is_not_a_probe(self):
        seen = []
        with mock.patch.object(status_report, "publish", side_effect=lambda **k: seen.append(k["probe"]) or {"ok": True, "tokens": 1, "cost_usd": None}), \
                mock.patch.object(cmd_status, "page"):
            quiet(cmd_status.publish, [])
            quiet(cmd_status.publish, ["--probe"])
        self.assertEqual([False, True], seen)


class TestDrainStatusEvents(unittest.TestCase):
    def test_a_drain_reports_begin_start_land_and_end_and_a_quiet_wait_rewrites_the_page(self):
        events = []

        class Io(FakeIo):
            def event(self, kind, issue=None, **info):
                events.append((kind, issue["number"] if issue else None))
                return "THREAD MESSAGE" if kind == "begin" else ""
        io = Io([drain_issue(1), drain_issue(2)], cap=1)
        _, out = quiet(cmd_drain.drain, io, drain_state(), sleep=lambda s: None)
        self.assertEqual([("begin", None), ("start", 1), ("land", 1), ("start", 2), ("land", 2), ("end", None)], events)
        self.assertIn("THREAD MESSAGE", out)

    def test_a_story_that_does_not_land_is_reported_held(self):
        events = []

        class Io(FakeIo):
            def event(self, kind, issue=None, **info):
                events.append(kind)
                return ""
        io = Io([drain_issue(1)], cap=1, land_ok=False)
        quiet(cmd_drain.drain, io, drain_state(), sleep=lambda s: None)
        self.assertIn("held", events)
        self.assertNotIn("land", events)

    def test_a_drain_with_a_long_build_ticks_at_the_rewrite_interval(self):
        events = []
        release = threading.Event()

        class Io(FakeIo):
            def build(self, i, wt, note):
                release.wait(5)
                return super().build(i, wt, note)

            def event(self, kind, issue=None, **info):
                events.append(kind)
                if kind == "tick":
                    release.set()
                return ""
        with mock.patch.object(cmd_drain, "REWRITE_SECONDS", 0.05):
            quiet(cmd_drain.drain, Io([drain_issue(1)], cap=1), drain_state(), sleep=lambda s: None)
        self.assertIn("tick", events)

    def test_io_event_passes_the_builder_limit_when_parallel_is_unset(self):
        seen = {}
        real = cmd_drain.Io(Path("/tmp/repo"), "o/r")
        with mock.patch.object(status_report, "record", lambda *a, **kw: seen.update(kw) or ""), \
                mock.patch.object(cmd_drain.local_config, "max_builders", return_value=3):
            real.event("begin")
        self.assertEqual(3, seen["builders"])


BOARD = {"repoOwner": "o", "repoName": "r", "fields": {"status": {"options": {"Backlog": "1", "Complete": "2"}}}}


def board_card(number: int, status: str) -> dict:
    return {"content": {"number": number, "repository": "o/r"}, "status": status}


class TestBoardRead(unittest.TestCase):
    """#1020: the repo's full issue list and the board are read again only when the open issues changed (cmd_boardsweep.read)."""

    def setUp(self):
        home = temp_dir(self)
        self.env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = home / "board.json"
        self.config.write_text(json.dumps(BOARD), encoding="utf-8")
        self.open_rows = [{"number": 1, "updated_at": "t1"}]
        self.rest = SimpleNamespace(repo_issues=mock.Mock(return_value=[{"number": 1, "state": "OPEN", "title": "t"}]))
        self.hygiene = SimpleNamespace(run_gh_soft=lambda args: json.dumps([self.open_rows]),
                                       load_items=mock.Mock(return_value=[board_card(1, "Backlog")]))
        patcher = mock.patch.dict(sys.modules, {"board_rest": self.rest, "check_board_hygiene": self.hygiene})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_unchanged_repo_rereads_no_issues_and_no_board(self):
        sweep.read(self.config)
        self.rest.repo_issues.reset_mock()
        self.hygiene.load_items.reset_mock()
        _, items, issues = sweep.read(self.config)
        self.rest.repo_issues.assert_not_called()
        self.assertEqual([{"number": 1, "state": "OPEN", "title": "t"}], issues)
        self.assertEqual([board_card(1, "Backlog")], items)

    def test_a_changed_open_issue_rereads_the_issues_and_the_board(self):
        sweep.read(self.config)
        self.open_rows.append({"number": 2, "updated_at": "t2"})
        self.rest.repo_issues.reset_mock()
        sweep.read(self.config)
        self.rest.repo_issues.assert_called_once()
        self.hygiene.load_items.assert_called_with(BOARD, use_cache=False)

    def test_an_unreadable_open_list_raises_without_rereading(self):
        self.hygiene.run_gh_soft = lambda args: None
        with self.assertRaises(RuntimeError):
            sweep.read(self.config)
        self.rest.repo_issues.assert_not_called()


class TestOwnerClears(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("OLIVERCODE_HOME")
        os.environ["OLIVERCODE_HOME"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("OLIVERCODE_HOME")
        else:
            os.environ["OLIVERCODE_HOME"] = self.old
        self.tmp.cleanup()

    def open_steps(self):
        return [i["step"] for i in cmd_owner.items() if i["status"] == "open"]

    def test_old_notes_are_dropped_from_the_file(self):
        cmd_owner.note("s", "fresh")
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
        cmd_owner._append({"id": 99, "created": old, "session": "s", "step": "old", "command": "", "error": "", "status": "info"})
        steps = [i["step"] for i in cmd_owner.items()]
        self.assertEqual(["fresh"], steps)
        self.assertNotIn("old", cmd_owner.path().read_text())

    def test_one_open_item_per_repo_with_the_latest_count(self):
        cmd_owner.add_once("f", "fleet-sync:r", "Bring r level with origin: 2 uncommitted file(s)", "c", "e")
        cmd_owner.add_once("f", "fleet-sync:r", "Bring r level with origin: 3 uncommitted file(s)", "c", "e")
        self.assertEqual(["Bring r level with origin: 3 uncommitted file(s)"], self.open_steps())

    def test_an_older_item_without_a_key_is_the_same_subject(self):
        cmd_owner.add("f", "Bring r level with origin: 2 uncommitted file(s)", "c", "e")
        cmd_owner.add_once("f", "fleet-sync:r", "Bring r level with origin: 3 uncommitted file(s)", "c", "e", prefix="Bring r level with origin")
        self.assertEqual(["Bring r level with origin: 3 uncommitted file(s)"], self.open_steps())

    def test_fleet_sync_closes_a_level_repo_and_keeps_a_dirty_one(self):
        repos = [("a", Path("a")), ("b", Path("b"))]
        results = {"a": ("2 uncommitted file(s)", "c", "e"), "b": ("2 uncommitted file(s)", "c", "e")}
        orig = cmd_fleetsync.sync_repo
        cmd_fleetsync.sync_repo = lambda path, check=None: results[path.name]
        try:
            cmd_fleetsync.run(repos, out=lambda t: None)
            results["a"] = ("level with origin", "", "")
            cmd_fleetsync.run(repos, out=lambda t: None)
        finally:
            cmd_fleetsync.sync_repo = orig
        self.assertEqual(["Bring b level with origin: 2 uncommitted file(s)"], self.open_steps())
        done = [i for i in cmd_owner.items() if i["status"] == "done"]
        self.assertEqual("the repo is level with origin", done[0]["reason"])

    def test_a_wait_on_a_closed_story_is_marked_done(self):
        cmd_owner.add("x", "Story #841 is finished", extra={})
        cmd_owner.add("x", "Story #900 is finished", extra={})
        cmd_owner.clear_stories("o/r", closed=lambda slug, n: n == 841)
        self.assertEqual(["Story #900 is finished"], self.open_steps())

    def test_a_wait_on_an_open_story_stays_open(self):
        cmd_owner.add("x", "Story #900 is finished", extra={})
        cmd_owner.clear_stories("o/r", closed=lambda slug, n: False)
        self.assertEqual(["Story #900 is finished"], self.open_steps())


class TestRerankClears(unittest.TestCase):
    def test_a_dropped_rerank_candidate_clears_its_state_and_is_refiled(self):
        stories = {n: {"number": n, "title": f"Imported {n}", "body": f"Source: gap-analysis-2.md (S{n}).\nPriority: P1. Size: S.", "labels": []} for n in range(1, 11)}
        mine, filed = {}, []
        args = ("o/r", stories, mine, 722)
        cmd_groom.review_imported(*args, run=lambda a: "", file=lambda *a: filed.append(a), queued=lambda slug, title: True)
        cmd_groom.review_imported(*args, run=lambda a: "", file=lambda *a: filed.append(a), queued=lambda slug, title: False)
        self.assertEqual(2, len(filed))
        self.assertEqual({"numbers": list(range(1, 11)), "seen": False}, mine["rerank"])


class RevampNumbersCase(unittest.TestCase):
    """#896: the four revamp numbers for the last seven days, printed by status and shown on the City page."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.handovers = self.root / "land"
        self.handovers.mkdir()
        self.repo = self.root / "work" / "repo-a"
        self.projects = self.root / "projects"
        self.folder = status_page.project_dir(self.repo, self.projects)
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def age(self, path, days):
        stamp = (NOW - timedelta(days=days)).timestamp()
        os.utime(path, (stamp, stamp))

    def transcript(self, name, entrypoint, days):
        path = self.folder / name
        path.write_text(json.dumps({"type": "user", "entrypoint": entrypoint}) + "\n", encoding="utf-8")
        self.age(path, days)

    def test_the_four_numbers_count_the_last_seven_days(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=4), dict(issue("2026-11-01", "2026-11-21"), number=5), dict(issue("2026-11-01"), number=6)]
        log = [{"story": "story-4", "input": 600, "output": 400}, {"story": "story-5", "input": 1000, "output": 0}]
        for name, days in (("handover-4.md", 1), ("handover-5.md", 30)):
            path = self.handovers / name
            path.write_text("# Story did not land\n", encoding="utf-8")
            self.age(path, days)
        self.transcript("a.jsonl", "cli", days=0.1)
        self.transcript("b.jsonl", "sdk-cli", days=0.1)
        self.transcript("c.jsonl", "cli", days=30)
        numbers = cmd_status.four_numbers(NOW, 14, rows, log, self.repo, self.projects, self.handovers)
        self.assertEqual({"tokens_per_closed": 1000, "handovers": 1, "threads": 1, "open": 14}, numbers)

    def test_run_prints_the_four_numbers_and_makes_no_model_call(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=4)]
        out = io.StringIO()
        with mock.patch.object(cmd_status, "run_log", return_value=[{"story": "story-4", "input": 10, "output": 5}]), \
                mock.patch.object(cmd_status.subprocess, "run", side_effect=AssertionError("no model call")):
            cmd_status.run("o/r", count=lambda s, state: 3, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"),
                           live=lambda now, count, rows: [], waiting=lambda: [], cands=lambda: "", folder=self.repo,
                           numbers=lambda: cmd_status.four_numbers(NOW, 3, rows, [{"story": "story-4", "input": 10, "output": 5}], self.repo,
                                                                    self.projects, self.handovers))
        self.assertIn("Revamp numbers, last 7 days: tokens per closed story 15, handovers 0, threads typed into 0, open stories 3.", out.getvalue())

    def test_no_closed_story_says_the_tokens_are_not_recorded(self):
        numbers = cmd_status.four_numbers(NOW, 2, [], [], self.repo, self.projects, self.handovers)
        self.assertIsNone(numbers["tokens_per_closed"])
        self.assertIn("tokens per closed story not recorded", cmd_status.numbers_line(numbers))


class TestDispatchTick(unittest.TestCase):
    def test_a_dispatch_beat_ticks_the_page_only_after_the_rewrite_interval(self):
        from lib import cmd_dispatch
        events = []
        fake = SimpleNamespace(refresh_claims=lambda: events.append("claims"), event=lambda kind, issue=None, **kw: events.append(kind) or "")
        beat = cmd_dispatch._beat_and_tick(fake, cmd_drain)
        beat()
        self.assertEqual(["claims"], events)
        with mock.patch("lib.cmd_dispatch.time.time", return_value=__import__("time").time() + cmd_drain.REWRITE_SECONDS + 1):
            beat()
        self.assertEqual(["claims", "claims", "tick"], events)


class TestOutsideLandings(unittest.TestCase):
    """#996: a commit that lands on a repo's main without the runner shows on the page, and a quiet page reads only git."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def closed(self, n, title="Seven", at=T0 - 600):
        return [{"number": n, "title": title, "closed_at": stamp(at)}]

    def test_a_commit_that_lands_outside_the_runner_shows_under_its_day_with_outside_the_runner_for_model_and_cost(self):
        with mock.patch.object(status_report, "main_commits", return_value=[(7, T0 - 600)]):
            found = status_report.outside_landings([], T0, repos=[("o/r", Path("/x"))], closed=lambda slug, since: self.closed(7))
        text = status_report.render({}, found, T0)
        self.assertEqual(["story-7"], [r["story"] for r in found])
        self.assertIn("#7 Seven", text)
        self.assertEqual(2, text.count("outside the runner"))
        self.assertIn("1 landed", text)

    def test_a_story_the_run_log_already_holds_is_not_read_from_github(self):
        log = [{"story": "story-7", "repo": "o/r", "round": 1, "at": stamp(T0 - 700)}]
        closed = mock.Mock(return_value=self.closed(7))
        with mock.patch.object(status_report, "main_commits", return_value=[(7, T0 - 600)]):
            found = status_report.outside_landings(log, T0, repos=[("o/r", Path("/x"))], closed=closed)
        self.assertEqual([], found)
        closed.assert_not_called()

    def test_a_repo_with_no_commit_on_main_reads_no_issue_list(self):
        closed = mock.Mock(return_value=[])
        with mock.patch.object(status_report, "main_commits", return_value=[]):
            self.assertEqual([], status_report.outside_landings([], T0, repos=[("o/r", Path("/x"))], closed=closed))
        closed.assert_not_called()

    def test_a_commit_whose_story_is_still_open_is_not_shown(self):
        with mock.patch.object(status_report, "main_commits", return_value=[(7, T0 - 600)]):
            found = status_report.outside_landings([], T0, repos=[("o/r", Path("/x"))], closed=lambda slug, since: [])
        self.assertEqual([], found)

    def test_main_commits_reads_origin_main_and_keeps_the_last_story_each_commit_names(self):
        done = mock.Mock(returncode=0, stdout=f"{int(T0)} Fix the thing (#7)\n{int(T0) - 5} Plain commit\n{int(T0) - 9} Two (#3) (#4)\n")
        with mock.patch.object(status_report.subprocess, "run", return_value=done) as run:
            found = status_report.main_commits(Path("/x"), datetime.fromtimestamp(T0, timezone.utc))
        self.assertIn("origin/main", run.call_args[0][0])
        self.assertEqual([(7, T0), (4, T0 - 9)], found)

    def test_a_repo_without_origin_main_reads_as_no_commits(self):
        with mock.patch.object(status_report.subprocess, "run", return_value=mock.Mock(returncode=128, stdout="")):
            self.assertEqual([], status_report.main_commits(Path("/x"), datetime.fromtimestamp(T0, timezone.utc)))

    def test_the_page_header_names_this_machine_and_the_last_rewrite(self):
        with mock.patch.object(status_report.platform, "node", return_value="test-machine"):
            text = status_report.render({}, [], T0)
        self.assertIn("This machine: test-machine.", text)
        self.assertIn("Last rewritten", text)

    def test_a_first_install_writes_an_empty_page_and_names_its_path(self):
        line = cmd_install.status_page_line()
        text = status_report.page_path().read_text(encoding="utf-8")
        self.assertIn(str(status_report.page_path()), line)
        self.assertIn("No run has started on this machine yet.", text)
        self.assertIn("[ALREADY]", cmd_install.status_page_line())

    def test_a_first_install_spends_no_live_github_read_on_citys_panel(self):
        """write_empty must not run City's panel: a fresh install has no repo registered yet to read (#1097)."""
        with mock.patch.object(status_report.subprocess, "run") as run:
            cmd_install.status_page_line()
        run.assert_not_called()
        self.assertNotIn("oc-term", status_report.page_path().read_text(encoding="utf-8"))

    def test_status_open_writes_a_missing_page_and_opens_it_from_any_folder(self):
        with mock.patch.object(status_report.subprocess, "run") as run, mock.patch("sys.stdout", new_callable=io.StringIO):
            code = cmd_status.command_status(["--open"])
        self.assertEqual(0, code)
        self.assertTrue(status_report.page_path().exists())
        self.assertEqual(str(status_report.page_path()), run.call_args[0][0][-1])


if __name__ == "__main__":
    unittest.main()
