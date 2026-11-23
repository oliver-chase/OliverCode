"""`olivercode status`: open count, landing rate and projected zero date from gh REST, with no model call."""

import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_status  # noqa: E402

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def issue(created: str, closed: str | None = None) -> dict:
    return {"created_at": created + "T00:00:00Z", "closed_at": closed + "T00:00:00Z" if closed else None}


class TestStatus(unittest.TestCase):
    def status(self, open_now, rows, slug="o/r"):
        out = io.StringIO()
        code = cmd_status.run(slug, count=lambda s, state: open_now, fetch=lambda s, since: rows, now=NOW, out=lambda t: out.write(t + "\n"),
                              live=lambda now, count, rows: [])
        return code, out.getvalue()

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

    def test_a_failed_read_exits_one(self):
        code, text = self.status(None, [])
        self.assertEqual(1, code)
        self.assertIn("were not read", text)

    def test_no_origin_exits_one(self):
        self.assertEqual(1, self.status(1, [], slug=None)[0])

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
        rows = [{"number": n, "title": f"Done {n}", "closed_at": f"2026-11-{10 + n}T00:00:00Z", "created_at": "2026-11-01T00:00:00Z"} for n in range(1, 8)]
        _, _, target = self.write([], [], rows=rows, opened=opened, waiting=["- #4 Approve the push"])
        body = target.read_text(encoding="utf-8")
        self.assertLess(body.index("P0 #9 First"), body.index("P2 #3 Low"))
        landed = body.split("## Landed, the last five\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(["- #7 Done 7 (2026-11-17)", "- #6 Done 6 (2026-11-16)", "- #5 Done 5 (2026-11-15)", "- #4 Done 4 (2026-11-14)", "- #3 Done 3 (2026-11-13)"], landed)
        self.assertIn("## Waits on the owner\n- #4 Approve the push", body)

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
        self.assertEqual(["Building #7 for 10 minutes on round 2.", "Last landed: #4 Done. Next Ready: P0 #9 First."], lines)

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


if __name__ == "__main__":
    unittest.main()
