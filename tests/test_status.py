"""`olivercode status`: open count, landing rate and projected zero date from gh REST, with no model call."""

import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_boardsweep as sweep  # noqa: E402
from lib import cmd_fleetsync, cmd_groom, cmd_owner, cmd_status  # noqa: E402

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def issue(created: str, closed: str | None = None) -> dict:
    return {"created_at": created + "T00:00:00Z", "closed_at": closed + "T00:00:00Z" if closed else None}


class TestStatus(unittest.TestCase):
    def status(self, open_now, rows, slug="o/r"):
        out = io.StringIO()
        code = cmd_status.run(slug, count=lambda s, state: open_now, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"),
                              live=lambda now, count, rows: [], waiting=lambda: [], cands=lambda: "")
        return code, out.getvalue()

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

    def test_the_tokens_per_closed_story_average_the_run_log_of_the_stories_that_closed(self):
        rows = [dict(issue("2026-11-01", "2026-11-20"), number=4), dict(issue("2026-11-01", "2026-11-21"), number=5), dict(issue("2026-11-01"), number=6)]
        log = [{"story": "story-4", "input": 600, "output": 400}, {"story": "story-4", "input": 1000, "output": 0},
               {"story": "story-5", "input": 1000, "output": 0}, {"story": "story-6", "input": 9000, "output": 0}]
        self.assertEqual("Tokens per closed story: 1,500 across 2 stories closed in the last 7 days.", cmd_status.tokens_per_story(rows, log))
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

    def test_a_building_story_is_one_line_with_its_time_round_last_landing_and_next_ready(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 600}}
        log = [{"story": "story-7", "round": 2, "at": "2026-11-21T23:58:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "P0 #9 First", {"number": 4, "title": "Done"})
        self.assertEqual([f"Building r #7: started {datetime.fromtimestamp(NOW.timestamp() - 600).strftime('%H:%M')}, 10 minutes ago, round 2 of 2, in validation and the fresh reader, no estimate yet.", "Last landed: #4 Done. Next Ready: P0 #9 First."], lines)

    def test_each_building_story_names_its_repo_size_state_minutes_and_what_holds_it(self):
        """#1112: a story waiting for validation names the slot's holder, and each other state reads from the run log, the holds and the queue."""
        t = NOW.timestamp()
        done = {"story": "story-1083", "round": 1, "at": "2026-11-21T23:56:00Z"}
        claims = {"o/OliverCode#1083": {"at": t - 900}}
        issues = {"1083": {"body": "Size: M"}}
        line = lambda **kw: cmd_status.state_lines(t, claims, kw.get("log", [done]), issues, kw.get("holder"), kw.get("slots", ["OliverCode-1084"]), 1,
                                                   kw.get("github", ""), kw.get("elsewhere", []), "o/OliverCode")
        self.assertEqual(["OliverCode #1083 · M · Waiting for validation · 4 min · slot held by OliverCode #1084"], line())
        self.assertEqual(["OliverCode #1083 · M · Reviewing · 4 min"], line(slots=["OliverCode-1083"]))
        self.assertEqual(["OliverCode #1083 · M · Landing · 4 min"], line(log=[{**done, "review": "pass"}]))
        self.assertEqual(["OliverCode #1083 · M · Building · 15 min"], line(log=[], slots=[]))
        self.assertEqual(["OliverCode #1083 · M · Waiting for GitHub · 15 min · the GraphQL rate limit"], line(log=[], github="held"))
        self.assertEqual(["OliverCode #1083 · M · Waiting for another repo · 15 min · digioperator holds the machine"],
                         line(log=[], holder={"building": [5]}, elsewhere=["o/digioperator"]))
        both = {**claims, "o/digioperator#824": {"at": t - 900}}
        self.assertEqual(["OliverCode #1083 · M · Building · 15 min", "digioperator #824 · Building · 15 min"],
                         cmd_status.state_lines(t, both, [], issues, {"building": [1083]}, [], 1, "", ["o/digioperator"], "o/OliverCode"))

    def test_status_names_a_graphql_hold_as_waiting_for_github(self):
        """#1112: run() stops on a REST hold, so the live lines read GraphQL's hold, the one the runner's board calls wait on."""
        with mock.patch.object(cmd_status, "runner_alive", return_value=True), mock.patch.object(cmd_status.gh_budget, "refusal", side_effect=lambda r="": "held" if r == "graphql" else ""), \
                mock.patch.object(cmd_status, "state_lines", return_value=[]) as lines, mock.patch.object(cmd_status, "live_claims", return_value={}), \
                mock.patch.object(cmd_status, "run_log", return_value=[]):
            cmd_status.live_lines(NOW, 0, [], "")
        self.assertEqual("held", lines.call_args.args[7])

    def test_builders_from_two_repos_each_name_their_repo_and_a_closed_story_is_dropped(self):
        """#1095: a claim's repo shows on its line, a claim for another repo's number holds nothing here, and a closed story is stale, not building."""
        claims = {"o/OliverCode#1031": {"agent": "drain", "at": NOW.timestamp() - 60}, "o/digioperator#824": {"agent": "drain", "at": NOW.timestamp() - 60}}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], True, 5, "", None)
        self.assertTrue(lines[0].startswith("Building OliverCode #1031"))
        self.assertTrue(lines[1].startswith("Building digioperator #824"))
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

    def test_minutes_count_from_the_claims_start_and_the_round_skips_rows_without_one(self):
        """#1093: a claim renewed every minute kept reading 0 or -1 minutes, and a row with no round printed round 0."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 26 * 60, "at": NOW.timestamp() + 5}}
        log = [{"story": "story-7", "round": 1}, {"story": "story-7"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None)
        self.assertIn("26 minutes ago, round 2 of 2,", lines[0])

    def test_a_new_story_is_round_1_and_an_earlier_run_does_not_set_the_round(self):
        """#1086: no finished round reads round 1, and rows logged before this claim began are a previous run's."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 60, "at": NOW.timestamp()}}
        old = [{"story": "story-7", "round": 2, "at": "2026-11-21T20:00:00Z"}]
        self.assertIn("1 minutes ago, round 1 of 2,", cmd_status.activity(NOW.timestamp(), claims, old, True, 5, "", None)[0])

    def test_a_small_story_shows_its_third_round_and_its_title(self):
        """#1086: a small story gets 3 rounds, so its third round reads round 3 of 3, with the story's title."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 600, "at": NOW.timestamp()}}
        log = [{"story": "story-7", "round": 2, "at": "2026-11-22T00:05:00Z"}]
        issues = {"7": {"number": 7, "title": "Small one", "body": "Size: S"}}
        line = cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None, None, issues)[0]
        self.assertIn("Building r #7, Small one: started", line)
        self.assertIn("round 3 of 3, in validation and the fresh reader", line)

    def test_minutes_count_from_the_start_when_the_claim_was_rewritten_a_minute_ago(self):
        """#1086: a claim posted again keeps its start, so 42 minutes of building read 42 minutes."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 42 * 60, "at": NOW.timestamp() - 60}}
        log = []
        self.assertIn("42 minutes ago, round 1 of 2,", cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None)[0])

    def test_the_line_names_the_phase_this_run_is_in(self):
        """#1086: a finished round of this run means validation and the reader, a passing review means landing, and an earlier run's rows say nothing."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 600, "at": NOW.timestamp()}}
        old = {"story": "story-7", "review": "pass", "at": "2026-11-21T20:00:00Z"}
        rnd = {"story": "story-7", "round": 1, "at": "2026-11-21T23:55:00Z"}
        review = {"story": "story-7", "review": "pass", "at": "2026-11-21T23:58:00Z"}
        for log, phase in (([old], "the builder session"), ([old, rnd], "validation and the fresh reader"), ([old, rnd, review], "landing")):
            self.assertIn(f"in {phase},", cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None)[0])

    def test_three_landed_stories_of_its_size_give_an_estimated_finish(self):
        """#1086: the median build minutes of landed stories of the same size, less the minutes spent, set the finish; fewer than 3 give none."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 600, "at": NOW.timestamp()}}
        issues = {"7": {"number": 7, "title": "Small one", "body": "Size: S"}}
        landed_rows = [{"story": f"story-{n}", "built_minutes": m, "size": "S"} for n, m in ((1, 20), (2, 40), (3, 100))]
        other = [{"story": "story-4", "built_minutes": 5, "size": "M"}]
        finish = datetime.fromtimestamp(NOW.timestamp() + 30 * 60).strftime("%H:%M")
        line = cmd_status.activity(NOW.timestamp(), claims, landed_rows + other, True, 5, "", None, None, issues)[0]
        self.assertIn(f"estimated finish {finish}.", line)
        line = cmd_status.activity(NOW.timestamp(), claims, landed_rows[:2] + other, True, 5, "", None, None, issues)[0]
        self.assertIn("no estimate yet.", line)

    def test_a_story_whose_log_and_commits_have_not_moved_says_so(self):
        """#1086: 45 minutes in with nothing new for 20 minutes, the line says so with the last thing it did, and a newer commit counts as a move."""
        claims = {"o/r#7": {"agent": "drain", "since": NOW.timestamp() - 45 * 60, "at": NOW.timestamp()}}
        log = [{"story": "story-7", "round": 1, "stop": "end_turn", "at": "2026-11-21T23:40:00Z"}]
        line = cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None)[0]
        self.assertIn("No progress for 20 minutes: the last thing it did was ending round 1 at", line)
        moved = cmd_status.activity(NOW.timestamp(), claims, log, True, 5, "", None, None, None, {"7": NOW.timestamp() - 120})[0]
        self.assertNotIn("No progress", moved)

    def test_build_history_spans_each_landed_story_log_rows(self):
        log = [{"story": "story-3", "at": "2026-11-21T10:00:00Z"}, {"story": "story-3", "at": "2026-11-21T10:30:00Z"}]
        rows = [{"number": 3, "closed_at": "2026-11-21T10:31:00Z", "body": "Size: S"}, {"number": 4, "body": "Size: S"}]
        self.assertEqual([{"size": "S", "built_minutes": 30.0}], cmd_status.build_history(rows, log))

    def test_an_idle_runner_says_so_and_names_the_command_that_starts_it(self):
        lines = cmd_status.activity(NOW.timestamp(), {}, [], False, 3, "", None)
        self.assertEqual(["Runner idle: no story is building and 3 stories are open. Start it with `olivercode drain REPO`.",
                          "Last landed: none in the last 7 days."], lines)

    def test_a_stalled_builder_is_warned_with_the_command_that_resumes_it(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 1, "", None)
        self.assertIn("the runner has stalled on #7", lines[-1])
        self.assertIn("olivercode dispatch 7", lines[-1])

    def test_a_stalled_claim_while_a_run_holds_the_repo_names_the_kill_that_releases_it_and_never_dispatch(self):
        """#1076: dispatch would only join the holding run's queue, so the warning names that run's kill instead."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 3600}}
        log = [{"story": "story-7", "round": 1, "at": "2026-11-21T22:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), claims, log, True, 1, "", None, {"pid": 4242, "who": "drain r"})
        self.assertIn("#7 holds a claim by drain with no progress for 60 minutes", lines[-1])
        self.assertIn("`kill 4242`", lines[-1])
        self.assertNotIn("dispatch", lines[-1])

    def test_a_last_run_that_stopped_badly_names_no_dispatch_while_a_run_holds_the_repo(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), {}, log, True, 2, "", None, {"pid": 4242, "who": "drain r"})
        self.assertEqual("Warning: the last run on story-5 stopped with max_turns.", lines[-1])

    def test_a_long_round_whose_runner_beat_a_minute_ago_is_not_stalled(self):
        """#1020: a claim 40 minutes old is building, not stalled, when the live holder is building it and its heartbeat is a minute old."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 2400}}
        holder = {"pid": 4242, "who": "drain r", "building": [7], "beat": NOW.timestamp() - 60}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], True, 1, "", None, holder)
        self.assertIn("40 minutes ago", lines[0])
        self.assertFalse(any("stalled" in line for line in lines))

    def test_a_long_round_whose_holder_is_not_building_it_is_stalled(self):
        """#1020: a live holder that is building another story does not keep a stalled claim from warning."""
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 2400}}
        holder = {"pid": 4242, "who": "drain r", "building": [8], "beat": NOW.timestamp() - 60}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], True, 1, "", None, holder)
        self.assertTrue(any(line.startswith("Warning: #7 holds a claim") for line in lines))

    def test_a_claim_without_a_live_runner_names_the_stale_claim_and_its_release(self):
        claims = {"o/r#7": {"agent": "drain", "at": NOW.timestamp() - 60}}
        lines = cmd_status.activity(NOW.timestamp(), claims, [], False, 1, "", None)
        self.assertIn("#7 holds a claim by drain but no drain or dispatch process is running", lines[-1])

    def test_a_last_run_that_did_not_stop_cleanly_is_warned_with_its_stop_reason(self):
        log = [{"story": "story-5", "round": 3, "stop": "max_turns", "at": "2026-11-23T11:00:00Z"}]
        lines = cmd_status.activity(NOW.timestamp(), {}, log, False, 2, "", None)
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


if __name__ == "__main__":
    unittest.main()
