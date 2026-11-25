"""`olivercode drain REPO`: ordering, skips, overlap, restarts, blocker comment and the summary line. Every effect is injected."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain, run_lock  # noqa: E402


def issue(n, body="", labels=(), title=None, status="Ready", size="S"):
    """A story Ready on the board and sized, with a Files area of its own unless the body names one (#1014)."""
    if "Files area:" not in body:
        body = f"{body}\nFiles area: scripts/story_{n}.py".lstrip()
    return {"number": n, "title": title or f"Story {n}", "body": body, "labels": [{"name": l} for l in labels], "comments": 0, "status": status, "size": size}


BATCH = {"body": "Built in a batch session with #976"}


class FakeIo:
    def __init__(self, issues, cap=2, builds=None, land_ok=True, tokens=10, stops=None):
        self.agent, self.moved, self.released, self.already, self.kept, self.on_main = "drain", [], [], False, [], set()
        self.ghost_land = False
        self.refuse_close = ""
        self.slug, self.issues, self.cap, self.builds, self.land_ok, self.tokens = "o/r", list(issues), cap, builds or {}, land_ok, tokens
        self.stops, self.owner = stops or {}, []  # story number -> the policy stop its builder hit; the owner-queue lines written
        self.closed, self.comments, self.started, self.claims, self.lock = [], [], [], set(), threading.Lock()
        self.active, self.peak_overlap = set(), []
        self.deps = {}  # story number -> the numbers of the stories that block it (#1064)
        self.leads = {}  # story number -> (sha, subject) of the lead commit its work landed under (#988)

    def landed_lead(self, i): return self.leads.get(i["number"])
    def told(self, n, sha): return (n, sha) in getattr(self, "toldof", set())

    def blockers(self, i):
        """The blockers of a story that are still open, as GitHub's dependency link would name them."""
        return [b for b in self.deps.get(i["number"], []) if b not in self.closed]

    def list_open(self):
        return [i for i in self.issues if i["number"] not in self.closed]

    def claimed(self, i): return i["number"] in self.claims
    def capacity(self):
        return self.cap.pop(0) if isinstance(self.cap, list) and len(self.cap) > 1 else (self.cap[0] if isinstance(self.cap, list) else self.cap)
    def limit(self): return 4
    def claim(self, n): pass
    def beat(self, building): self.beats = getattr(self, "beats", []) + [list(building)]
    def worktree(self, n): return Path(f"/wt/{n}")
    repo = Path("/repo")
    def pending(self, n): return False
    no_validation = False
    def validation(self): return None if self.no_validation else ["bash", "scripts/validate.sh"]

    def build(self, i, wt, note):
        n = i["number"]
        with self.lock:
            self.started.append(n)
            self.active.add(n)
            self.peak_overlap.append(set(self.active))
        script = self.builds.get(n)
        out = script.pop(0) if script else {"done": True, "reason": "ok", "tokens": self.tokens}
        with self.lock:
            self.active.discard(n)
        return {"tokens": self.tokens, **out}

    def commits(self, wt): return 1
    def land(self, wt, n):
        if self.land_ok and not self.ghost_land:
            self.on_main.add(n)
        return self.land_ok, "RESULT pushed abc1234" if self.land_ok else "RESULT validate-failed"
    def comment(self, n, body): self.comments.append((n, body))
    def close_by_script(self, wt, n, why):
        if self.refuse_close:
            return False, self.refuse_close
        self.closed.append(n)
        self.moved.append(n)
        return True, ""
    def release(self, n): self.released.append(n)
    def keep_open(self, n, reason=""): self.kept.append(n)
    def backlog(self, n): self.parked = getattr(self, "parked", []) + [n]
    def landed(self, wt, n): return self.already or (n in self.on_main)
    def policy_stop(self, n, wt): return self.stops.get(n)
    def queue_owner(self, n, stop): self.owner.append((n, stop))


def state():
    return {"closed": [], "blocked": [], "sessions": 0, "tokens": 0, "restarts": {}}


class DrainCase(unittest.TestCase):
    def run_drain(self, io, st=None):
        st = st or state()
        code, out = quiet(cmd_drain.drain, io, st, sleep=lambda s: None)
        return code, out, st

    def test_api_errors_back_off_exponentially_without_consuming_builder_restarts(self):
        errors = [{"done": False, "api_error": True, "api_error_cause": "529 overloaded_error", "reason": "API error", "tokens": 0} for _ in range(2)]
        io = FakeIo([issue(1)], cap=1, builds={1: errors + [{"done": True, "reason": "ok", "tokens": 1}]})
        sleeps = []
        with mock.patch.object(cmd_drain.time, "sleep", side_effect=sleeps.append):
            code, out, st = self.run_drain(io)
        self.assertEqual(0, code)
        self.assertEqual([60, 120], sleeps)
        self.assertEqual([1], io.closed)
        self.assertEqual(3, st["sessions"])
        self.assertEqual(0, st["api_error_streak"])

    def test_five_consecutive_api_errors_stop_the_drain_with_the_cause(self):
        errors = [{"done": False, "api_error": True, "api_error_cause": "529 overloaded_error", "reason": "API error", "tokens": 0} for _ in range(5)]
        io = FakeIo([issue(1)], cap=1, builds={1: errors})
        sleeps = []
        with mock.patch.object(cmd_drain.time, "sleep", side_effect=sleeps.append):
            code, out, st = self.run_drain(io)
        self.assertEqual(1, code)
        self.assertEqual([60, 120, 240, 480], sleeps)
        self.assertIn("five consecutive API errors", out)
        self.assertIn("529 overloaded_error", out)
        self.assertEqual("529 overloaded_error", st["api_error_stop"])

    def test_orders_p0_first_and_skips_epics_claimed_and_owner_gated(self):
        io = FakeIo([issue(1, "Priority: P2"), issue(2, "Priority: P0"), issue(3, "Work type: Epic"), issue(4, labels=["owner-gate"]), issue(5), issue(6, "Priority: P1")], cap=1)
        io.claims.add(5)
        code, out, st = self.run_drain(io)
        self.assertEqual(io.started, [2, 6, 1])
        self.assertEqual(io.closed, [2, 6, 1])
        self.assertIn("Drain done: 3 stories closed", out)
        self.assertEqual(code, 0)

    def test_two_stories_on_one_file_build_at_the_same_time(self):
        """#1080: a shared file no longer holds a story back; the landing's rebase is the guard. The barrier only opens with both builders live."""
        gate = threading.Barrier(2, timeout=5)
        io = FakeIo([issue(1, "Files area: scripts/lib/cmd_install.py"), issue(2, "Files area: scripts/lib/cmd_install.py")], cap=4)
        build = io.build
        io.build = lambda i, wt, note: (gate.wait(), build(i, wt, note))[1]
        self.run_drain(io)
        self.assertEqual(sorted(io.closed), [1, 2])

    def test_a_rebase_conflict_restarts_the_builder_with_the_fix_named(self):
        """#1080: the builder is told to rebase onto the default branch and keep both changes."""
        io = FakeIo([issue(1)], cap=1)
        notes, results = [], ["RESULT rebase-conflict", "RESULT pushed abc1234"]
        build = io.build
        io.build = lambda i, wt, note: (notes.append(note), build(i, wt, note))[1]
        io.land = lambda wt, n: (io.on_main.add(n) or True, results.pop(0)) if results[0].endswith("abc1234") else (False, results.pop(0))
        self.run_drain(io)
        self.assertEqual([1], io.closed)
        self.assertIn("rebase onto origin", notes[1])
        self.assertIn("keep both", notes[1])

    def test_only_ready_sized_stories_with_a_files_area_are_built_and_each_skip_is_named_once(self):
        io = FakeIo([issue(1, status="Backlog"), issue(2, size=""), {**issue(3), "body": "Priority: P0"}, issue(4)], cap=4)
        code, out, _ = self.run_drain(io)
        self.assertEqual(io.started, [4])
        self.assertIn("Skipped #1: its board Status is Backlog, not Ready.", out)
        self.assertIn("Skipped #2: it has no Size on the board.", out)
        self.assertIn("Skipped #3: it names no Files area.", out)
        self.assertEqual(1, out.count("Skipped #1:"))
        self.assertEqual(code, 0)

    def test_a_blocked_story_waits_and_names_its_blocker(self):
        io = FakeIo([issue(1), issue(2)], cap=1)
        io.deps = {1: [9]}
        code, out, _ = self.run_drain(io)
        self.assertEqual(io.started, [2])
        self.assertIn("Skipped #1: it is blocked by open #9.", out)
        self.assertEqual(1, out.count("Skipped #1:"))

    def test_a_story_whose_blocker_closes_runs_in_priority_order(self):
        io = FakeIo([issue(1, "Priority: P0"), issue(2, "Priority: P1")], cap=1)
        io.deps = {1: [2]}
        code, out, _ = self.run_drain(io)
        self.assertEqual(io.started, [2, 1])
        self.assertIn("Skipped #1: it is blocked by open #2.", out)

    def test_the_default_blockers_read_only_open_ones_and_skip_the_call_when_none_are_open(self):
        calls = []

        def gh(args):
            calls.append(args)
            rows = [{"number": 7, "state": "open"}, {"number": 8, "state": "closed"}]
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rows), stderr="")

        io = cmd_drain.Io(Path("/repo"), "o/r", runner=gh)
        self.assertEqual([], io.blockers({"number": 1}))
        self.assertEqual([], io.blockers({"number": 1, "issue_dependencies_summary": {"blocked_by": 0, "total_blocked_by": 2}}))
        self.assertEqual([], calls)
        self.assertEqual([7], io.blockers({"number": 1, "issue_dependencies_summary": {"blocked_by": 1}}))
        self.assertEqual(["api", "repos/o/r/issues/1/dependencies/blocked_by"], calls[0])

    def test_a_repo_with_no_validation_is_refused_before_any_builder_starts(self):
        io = FakeIo([issue(1)], cap=1)
        io.no_validation = True
        code, out, st = self.run_drain(io)
        self.assertEqual((io.started, st["blocked"]), ([], [1]))
        self.assertIn("Fix: add scripts/validate.sh", io.comments[0][1])

    def test_a_reason_a_restart_cannot_fix_blocks_the_story_without_a_new_session(self):
        io = FakeIo([issue(1)], cap=1, builds={1: [{"done": False, "fatal": True, "reason": "nothing checked the result"}]})
        code, out, st = self.run_drain(io)
        self.assertEqual((io.started, st["blocked"], st["sessions"]), ([1], [1], 1))

    def test_restarts_an_early_exit_then_lands(self):
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "claude exited 1"}, {"done": False, "reason": "claude exited 1"}]})
        _, out, st = self.run_drain(io)
        self.assertEqual(io.started, [1, 1, 1])
        self.assertEqual(io.closed, [1])
        self.assertEqual(st["sessions"], 3)

    def test_comments_the_blocker_after_three_restarts_and_moves_on(self):
        dead = {"done": False, "reason": "out of budget"}
        io = FakeIo([issue(1, "Priority: P0"), issue(2)], cap=1, builds={1: [dict(dead) for _ in range(4)]})
        _, out, st = self.run_drain(io)
        self.assertEqual(io.started.count(1), 4)
        self.assertEqual(io.closed, [2])
        self.assertEqual([n for n, _ in io.comments if n == 1], [1])
        self.assertIn("out of budget", io.comments[0][1])
        self.assertEqual(st["blocked"], [1])

    def test_a_mate_whose_work_landed_under_a_lead_is_not_built_again(self):
        """#988: no builder starts, the story stays open on Ready, and one comment names the lead commit for the owner."""
        io = FakeIo([issue(1)])
        io.leads[1] = ("0123456789ab", "Fix the thing (#976)")
        _, _, st = self.run_drain(io)
        self.assertEqual([], io.started)
        self.assertEqual([1], io.kept)
        self.assertEqual([1], st["blocked"])
        self.assertIn("Fix the thing (#976)", io.comments[0][1])

    def test_the_default_drain_fills_the_machine_limit_and_parallel_overrides_it(self):
        """#1055: with no flag a drain runs up to maxBuilders less what other repos build; --parallel N wins; a bad N is refused."""
        with mock.patch.object(cmd_drain.local_config, "max_builders", return_value=4), \
                mock.patch.object(cmd_drain.run_lock, "building_elsewhere", return_value=3):
            self.assertEqual(1, cmd_drain.Io(Path("/nonexistent"), "o/r").capacity())
            self.assertEqual(3, cmd_drain.Io(Path("/nonexistent"), "o/r", parallel=3).capacity())
        with mock.patch.object(cmd_drain.local_config, "max_builders", return_value=4), \
                mock.patch.object(cmd_drain.run_lock, "building_elsewhere", return_value=6):
            self.assertEqual(0, cmd_drain.Io(Path("/nonexistent"), "o/r").capacity())
        seen = []
        factory = lambda repo, slug, parallel=None: seen.append(parallel) or FakeIo([])
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/nonexistent")), mock.patch.object(cmd_drain, "backlog_config",
                                                                                                             return_value={"repoOwner": "o", "repoName": "r"}):
            quiet(cmd_drain.command_drain, ["r"], factory, lambda s: None)
            quiet(cmd_drain.command_drain, ["r", "--parallel", "2"], factory, lambda s: None)
            code, _ = quiet(cmd_drain.command_drain, ["r", "--parallel", "0"], factory, lambda s: None)
        self.assertEqual([None, 2], seen)
        self.assertEqual(2, code)

    def test_a_story_whose_files_area_names_a_folder_is_skipped_and_the_rest_run(self):
        """#1077: a folder-wide area overlapped every story and held a 4-builder drain to 1."""
        repo = temp_dir(self)
        (repo / "scripts" / "lib").mkdir(parents=True)
        wide = issue(1, body="Files area: scripts/lib, tests")
        self.assertIn("names the folder scripts/lib", cmd_drain.skip_reason(wide, repo))
        self.assertEqual("", cmd_drain.skip_reason(issue(2), repo))
        io = FakeIo([wide, issue(2), issue(3)], cap=4)
        io.repo = repo
        _, out, _ = self.run_drain(io)
        self.assertEqual({2, 3}, set(io.started))
        self.assertIn("Skipped #1", out)

    def test_a_full_machine_waits_for_a_free_builder_and_never_reads_the_load(self):
        """#1055: no free builder means wait, then start; the load average plays no part."""
        io = FakeIo([issue(1)], cap=[0, 0, 1])
        naps = []
        with mock.patch.object(cmd_drain.cmd_dispatch, "machine_load", side_effect=AssertionError("load read"), create=True):
            quiet(cmd_drain.drain, io, cmd_drain.new_state(), sleep=naps.append)
        self.assertEqual(([1], 1), (io.started, len(naps)))

    def test_a_held_story_is_not_restarted_or_pushed_and_one_comment_holds_the_finding(self):
        io = FakeIo([issue(1)], builds={1: [{"done": False, "held": "scripts/a.py: no test"}]})
        _, _, st = self.run_drain(io)
        self.assertEqual(io.started, [1])
        self.assertEqual(set(), io.on_main)
        self.assertEqual(io.kept, [1])
        self.assertEqual(st["blocked"], [1])
        self.assertEqual([1], [n for n, _ in io.comments])
        self.assertIn("scripts/a.py: no test", io.comments[0][1])
        self.assertIn("nothing was pushed", io.comments[0][1])

    def test_a_policy_stopped_builder_is_not_restarted_and_the_owner_hears_once(self):
        stop = {"rule": "triggers.gateFailures", "gate": "Owner identifiers", "finding": "scripts/lib/x.py:4 owner identifier", "file": "scripts/lib/x.py"}
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "commit refused"}]}, stops={1: stop})
        _, out, st = self.run_drain(io)
        self.assertEqual(io.started, [1])
        self.assertEqual(st["blocked"], [1])
        self.assertEqual(io.kept, [1])
        self.assertEqual([(1, stop)], io.owner)
        self.assertEqual([1], [n for n, _ in io.comments])
        body = io.comments[0][1]
        for part in ("Gate: Owner identifiers", "Last finding: scripts/lib/x.py:4 owner identifier", "File: scripts/lib/x.py", "Next: run the diagnosing-bugs loop"):
            self.assertIn(part, body)

    def test_the_1012_failure_log_replays_to_one_comment_and_no_restart(self):
        """#1058: five owner-identifier blocks then six policy asks, all on OliverCode-1012. Before the fix drain restarted three times."""
        home = temp_dir(self)
        log = home / "failures.log"
        rows = [f"2026-11-23T16:{m:02d}:{s:02d}Z\tOliverCode-1012\tOwner identifiers\tscripts/lib/owner.py:9 owner identifier found\n" for m, s in ((12, 0), (13, 0), (14, 0), (15, 0), (16, 0))]
        rows += [f"2026-11-23T16:{m:02d}:00Z\tOliverCode-1012\tpolicy\task triggers.gateFailures\n" for m in range(19, 27)]
        log.write_text("".join(rows), encoding="utf-8")

        class Replay(FakeIo):
            def policy_stop(self, n, wt):
                return cmd_drain.policy_stop_in("OliverCode-1012", "2026-11-23T16:12:00Z")

        io = Replay([issue(1012)], builds={1012: [{"done": False, "reason": "commit refused"} for _ in range(4)]})
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            _, out, st = self.run_drain(io)
        self.assertEqual(io.started, [1012])
        self.assertEqual(1, len(io.comments))
        self.assertIn("File: scripts/lib/owner.py", io.comments[0][1])
        self.assertEqual(st["blocked"], [1012])

    def test_a_stop_with_no_policy_ask_in_the_run_is_not_a_stop(self):
        log_home = temp_dir(self)
        log = log_home / "failures.log"
        log.write_text("2026-11-23T16:12:00Z\tOliverCode-1012\tOwner identifiers\tscripts/lib/owner.py:9 found\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            self.assertIsNone(cmd_drain.policy_stop_in("OliverCode-1012", "2026-11-23T16:00:00Z"))

    def test_the_owner_line_is_written_once_per_story_and_names_the_gate(self):
        home = temp_dir(self)
        stop = {"rule": "triggers.gateFailures", "gate": "Owner identifiers", "finding": "", "file": ""}
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            io = cmd_drain.Io(Path("/repo"), "o/r")
            io.queue_owner(1012, stop)
            io.queue_owner(1012, stop)
            from lib import cmd_owner
            open_steps = [i for i in cmd_owner.items() if i["status"] == "open"]
        self.assertEqual(1, len(open_steps))
        self.assertIn("Story #1012 waits on you", open_steps[0]["step"])
        self.assertIn("at the Owner identifiers gate", open_steps[0]["step"])

    def test_failed_landing_counts_as_a_restart(self):
        io = FakeIo([issue(1)], land_ok=False)
        self.run_drain(io)
        self.assertEqual(io.started, [1, 1, 1, 1])
        self.assertEqual(io.closed, [])
        self.assertIn("validate-failed", io.comments[-1][1])

    def test_a_drain_writes_no_handoff_and_stops_for_no_token_total(self):
        io = FakeIo([issue(n) for n in range(1, 6)], cap=1, tokens=1_000_000)
        code, out, st = self.run_drain(io)
        self.assertEqual((0, io.closed), (code, [1, 2, 3, 4, 5]))
        self.assertIn("Drain done: 5 stories closed", out)
        self.assertNotIn("andoff", out)
        self.assertFalse(any(hasattr(cmd_drain, name) for name in ("HANDOFF_TOKENS", "write_handoff", "read_handoff", "handoff_path")))

    def test_a_landed_story_closes_through_the_script_with_no_builder_session(self):
        io = FakeIo([issue(1)])
        io.already = True
        io.land = lambda wt, n: self.fail("land ran for a story that was already on the default branch")
        self.run_drain(io)
        self.assertEqual(([], [1], [1]), (io.started, io.closed, io.moved))

    def test_a_refused_close_of_a_landed_story_leaves_the_card_where_it_is(self):
        io = FakeIo([issue(1)])
        io.already, io.refuse_close = True, "complete_story: #1 not completed"
        _, _, st = self.run_drain(io)
        self.assertEqual(([], [], [1]), (io.started, io.closed, st["blocked"]))
        self.assertEqual([], io.kept)
        self.assertIn("Close refused by complete_story.py", io.comments[0][1])

    def test_new_commits_land_before_the_landed_shortcut_and_no_commit_takes_it_only_when_main_holds_the_story(self):
        io = FakeIo([issue(1)])
        io.already = True
        landed = []
        io.land = lambda wt, n: landed.append(n) or (True, "RESULT pushed")
        self.assertEqual((True, "RESULT pushed"), cmd_drain.land_and_close(io, Path("/wt/1"), 1))
        self.assertEqual([1], landed)
        io.commits = lambda wt: 0
        self.assertEqual((True, "already on the default branch"), cmd_drain.land_and_close(io, Path("/wt/1"), 1))
        self.assertEqual([1], landed)
        io.already = False
        self.assertFalse(cmd_drain.land_and_close(io, Path("/wt/1"), 1)[0])

    def test_one_crashed_worker_blocks_its_story_and_the_others_continue(self):
        io = FakeIo([issue(1, "Priority: P0"), issue(2)], cap=1)
        real = io.build
        def build(i, wt, note):
            if i["number"] == 1:
                raise ValueError("boom")
            return real(i, wt, note)
        io.build = build
        code, _, st = self.run_drain(io)
        self.assertEqual((0, [1], [2]), (code, st["blocked"], st["closed"]))
        self.assertIn(1, io.released)
        self.assertTrue(any(n == 1 and "boom" in body for n, body in io.comments))

    def test_a_landing_that_puts_nothing_on_the_default_branch_closes_nothing(self):
        io = FakeIo([issue(1)])
        io.ghost_land = True
        self.run_drain(io)
        self.assertEqual((io.closed, io.moved, io.kept), ([], [], [1]))

    def test_a_story_of_size_l_or_xl_is_skipped_and_named(self):
        for size in ("L", "XL"):
            reason = cmd_drain.skip_reason(issue(1, size=size))
            self.assertIn(f"Size {size}", reason)
            self.assertIn("split", reason)
        self.assertEqual(cmd_drain.skip_reason(issue(1, size="M")), "")

    def test_a_story_that_stops_on_the_turn_limit_twice_is_parked_and_the_next_story_builds(self):
        spent = {"done": False, "reason": "max_turns", "budget": True}
        io = FakeIo([issue(1, "Priority: P0"), issue(2)], cap=1, builds={1: [dict(spent) for _ in range(4)]})
        _, _, st = self.run_drain(io)
        self.assertEqual(io.started.count(1), 2)  # no third restart
        self.assertEqual(io.parked, [1])
        self.assertEqual((io.closed, io.kept), ([2], []))
        self.assertIn(1, io.released)
        self.assertTrue(any(n == 1 and body.startswith("Parked:") for n, body in io.comments))

    def test_a_turn_limit_stop_followed_by_another_failure_is_not_parked(self):
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "x", "budget": True},
                                             {"done": False, "reason": "claude exited 1"},
                                             {"done": False, "reason": "x", "budget": True},
                                             {"done": False, "reason": "y"}]})
        self.run_drain(io)
        self.assertEqual(io.started.count(1), 4)
        self.assertFalse(getattr(io, "parked", []))

    def test_a_blocked_story_stays_open_and_returns_to_ready(self):
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "claude exited 1 in round 1."} for _ in range(4)]})
        self.run_drain(io)
        self.assertEqual((io.closed, io.kept), ([], [1]))

    def test_the_claim_is_released_after_a_landing_and_after_a_blocker(self):
        io = FakeIo([issue(1), issue(2)], cap=1, builds={2: [{"done": False, "reason": "out of budget"} for _ in range(4)]})
        self.run_drain(io)
        self.assertEqual((io.closed, io.moved, sorted(io.released)), ([1], [1], [1, 2]))

    def test_empty_board_prints_one_summary_line(self):
        code, out, _ = self.run_drain(FakeIo([]))
        self.assertEqual(out.strip(), "Drain done: 0 stories closed, 0 blocked, 0 sessions, 0 tokens.")

    def test_unreadable_board_stops(self):
        io = FakeIo([])
        io.list_open = lambda: None
        code, out, _ = self.run_drain(io)
        self.assertEqual(code, 1)

    def test_command_refuses_bad_arguments(self):
        self.assertEqual(quiet(cmd_drain.command_drain, [])[0], 2)
        self.assertEqual(quiet(cmd_drain.command_drain, ["/nonexistent-repo-xyz"])[0], 1)


class TestDrainClaims(unittest.TestCase):
    """#710: the real Io skips a live claim and writes its claim before a builder starts."""

    def setUp(self):
        home, self.repo = temp_dir(self), temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        scratch_repo(self.repo, branch="main")
        git(self.repo, "commit", "--allow-empty", "-qm", "base")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.io = cmd_drain.Io(self.repo, "o/r")
        self.posted = []
        stamp = cmd_drain.time.strftime("%Y-%m-%dT%H:%M:%SZ", cmd_drain.time.gmtime())
        self.rows = [{"body": f"Claim\n- Session: b1\n- Time: {stamp}"}]

        def gh(args):
            if args[0] == "api" and "-f" not in args and "-X" not in args and not any(a.startswith("body=") for a in args):
                return subprocess.CompletedProcess(args, 0, json.dumps(self.rows), "")
            self.posted.append(args)
            return subprocess.CompletedProcess(args, 0, "https://example.test/c/1\n", "")
        p2 = mock.patch.object(cmd_drain.cmd_dispatch, "gh", gh)
        p2.start()
        self.addCleanup(p2.stop)

    def test_a_live_claim_from_another_session_is_skipped(self):
        self.assertTrue(self.io.claimed(issue(5) | {"comments": 1}))
        self.assertEqual(self.posted, [])


class TestRealIo(unittest.TestCase):
    """How a headless builder finishes a story (docs/SETUP.md), #877: the real Io builds the real brief, makes a prepared worktree and reads the landing from git."""

    def setUp(self):
        home, self.repo = temp_dir(self), temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        scratch_repo(self.repo, branch="main")
        git(self.repo, "commit", "--allow-empty", "-qm", "base")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.io = cmd_drain.Io(self.repo, "o/r")

    def test_the_brief_is_built_by_the_real_rules_without_a_missing_key(self):
        seen = {}
        with mock.patch.object(cmd_drain.agent_loop, "run_loop", lambda brief, wt, name, **kw: seen.update(brief=brief) or {"done": True}):
            self.io.build(issue(7, "Do the thing."), Path("/wt/7"), "")
        self.assertIn("Story #7: Story 7", seen["brief"])
        self.assertIn("Builder rules:", seen["brief"])
        self.assertIn("Commit and stop", seen["brief"])
        self.assertNotIn("olivercode land WORKTREE", seen["brief"])

    def test_the_model_follows_the_story_size_and_a_small_story_gets_a_third_round(self):
        for size, labels, model_name, rounds in (("XS", [], "haiku", 3), ("L", [], "sonnet", 2), ("M", ["design"], "opus", 2)):
            with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
                self.io.build(issue(7, f"Do it.\nSize: {size}", labels=labels), Path("/wt/7"), "")
            self.assertEqual((model_name, rounds), (run_loop.call_args.kwargs["model_name"], run_loop.call_args.kwargs["rounds"]), size)

    def test_the_turn_budget_follows_the_story_size(self):
        for size, turns in (("XS", 30), ("S", 30), ("M", 30), ("L", 30)):
            with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
                self.io.build(issue(7, f"Do it.\nSize: {size}"), Path("/wt/7"), "")
            self.assertEqual(turns, run_loop.call_args.kwargs["max_turns"], size)

    def test_a_spent_budget_leaves_a_handoff_comment_and_the_next_round_starts_from_it(self):
        spent = {"done": False, "budget": True, "reason": "claude exited 1, stop reason max_turns", "summary": "Wrote the parser; tests are left."}
        notes = []
        io = FakeIo([issue(1)], builds={1: [spent]})
        build = io.build
        io.build = lambda i, wt, note: notes.append(note) or build(i, wt, note)
        _, out, st = DrainCase.run_drain(self, io)
        self.assertEqual(io.closed, [1])
        self.assertIn("Budget reached: the builder used every turn", io.comments[0][1])
        self.assertIn("Left: Wrote the parser; tests are left.", io.comments[0][1])
        self.assertIn("Left: Wrote the parser", notes[1])

    def test_the_brief_carries_the_resume_note_and_names_no_other_story(self):
        lead = issue(7, "Do it.\nSize: XS")
        self.io.resumed[7] = "Earlier partial work is present on branch story/7."
        with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
            self.io.build(lead, Path("/wt/7"), "")
        brief = run_loop.call_args.args[0]
        self.assertIn("Earlier partial work is present on branch story/7.", brief)
        self.assertNotIn("share files", brief)

    def test_the_claim_posts_through_the_runner_as_the_agent_and_a_held_budget_queues_the_card(self):
        posted, queued = [], []
        self.io = cmd_drain.Io(self.repo, "o/r", "dispatch", lambda args: posted.append(args) or subprocess.CompletedProcess(args, 0, "https://example.test/c/1\n", ""))
        self.io.claim(7)
        self.assertIn("Claim\n- Session: dispatch", " ".join(posted[0]))
        self.assertEqual("held by dispatch", cmd_drain.cmd_dispatch._local_claim("o/r", 7, cmd_drain.time.time()))
        cfg = {"repoOwner": "o"}
        with mock.patch.object(cmd_drain.gh_budget, "refusal", return_value="held"), mock.patch.object(cmd_drain, "backlog_config", lambda repo: cfg), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: queued.extend(fn([])[1])):
            self.io.claim(8)
        self.assertEqual(1, len(posted))
        self.assertEqual([{"cfg": cfg, "issues": [{"number": 8, "fields": {"status": "In Progress"}}]}], queued)

    def test_the_worktree_comes_from_the_shared_preparing_function(self):
        calls = []
        wt_root = temp_dir(self)
        with mock.patch.object(cmd_drain, "placement_config", lambda: mock.Mock(worktrees=wt_root)), \
                mock.patch.object(cmd_drain.cmd_land, "add_worktree", lambda repo, wt, n, base: calls.append((n, base)) or []):
            self.io.worktree(7)
        self.assertEqual(calls, [("7", "origin/main")])
        with mock.patch.object(cmd_drain, "placement_config", lambda: mock.Mock(worktrees=wt_root)), \
                mock.patch.object(cmd_drain.cmd_land, "add_worktree", lambda *a: ["hooks failed"]):
            with self.assertRaises(RuntimeError):
                self.io.worktree(8)

    def test_a_new_worktree_commit_lands_even_when_an_older_commit_on_main_names_the_story(self):
        """#1011: the old (#7) commit makes landed() true, yet the worktree's own commit is what lands."""
        self.commit_file("old.txt", "Earlier work (#7)")
        wt = temp_dir(self) / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "story/7", str(wt), "origin/main")
        (wt / "new.txt").write_text("new\n")
        git(wt, "add", "new.txt")
        git(wt, "commit", "-qm", "More work (#7)")
        self.assertTrue(self.io.landed(wt, 7))
        self.assertEqual(1, self.io.commits(wt))
        pushed = []
        def land(worktree, n):
            pushed.append(git(worktree, "rev-parse", "HEAD").stdout.strip())
            git(self.repo, "update-ref", "refs/remotes/origin/main", pushed[0])
            return True, "RESULT pushed"
        self.io.land, self.io.close_by_script = land, lambda *a: (True, "")
        self.assertEqual((True, "RESULT pushed"), cmd_drain.land_and_close(self.io, wt, 7))
        self.assertEqual(1, len(pushed))
        self.assertEqual(pushed[0], git(self.repo, "rev-parse", "origin/main").stdout.strip())

    def test_the_landed_shortcut_runs_on_the_real_io_and_yields_to_unlanded_worktree_commits(self):
        """#1011: a landed story closes from the repo with no builder, but a worktree holding new commits is built and landed instead."""
        self.commit_file("old.txt", "Earlier work (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        closes = []
        self.io.close_by_script = lambda wt, n, why: closes.append(wt) or (True, "")
        self.io.landed_lead = lambda issue: None
        self.io.landed = lambda wt, n: True
        self.assertFalse(self.io.pending(7))
        self.assertEqual((True, 0), cmd_drain._work_story(self.io, issue(7), state()))
        self.assertEqual([self.repo], closes)
        wt = cmd_drain.placement_config().worktrees / f"{self.repo.name}-7"
        git(self.repo, "worktree", "add", "-q", "-b", "story/7", str(wt), "origin/main")
        self.addCleanup(lambda: git(self.repo, "worktree", "remove", "--force", str(wt)))
        (wt / "new.txt").write_text("new\n")
        git(wt, "add", "new.txt")
        git(wt, "commit", "-qm", "More work (#7)")
        self.assertTrue(self.io.pending(7))

    def commit_file(self, path: str, subject: str) -> None:
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(subject + "\n", encoding="utf-8")
        git(self.repo, "add", path)
        git(self.repo, "commit", "-qm", subject)
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    def mate_io(self, notes: list) -> cmd_drain.Io:
        """An Io whose REST reads return the story's comments as `notes`."""
        return cmd_drain.Io(self.repo, "o/r", "dispatch", lambda args: subprocess.CompletedProcess(args, 0, json.dumps(notes), ""))

    def test_a_mate_is_recognized_when_a_lead_commit_changed_its_files_and_its_close_was_refused(self):
        """#988: the lead commit is named, and the mate's work is not built again."""
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the thing (#976)")
        mate = {**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}, BATCH]
        lead = self.mate_io(refused).landed_lead(mate)
        self.assertEqual("Fix the thing (#976)", lead[1])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), lead[0])

    def test_a_story_is_built_as_before_without_a_refused_close_an_overlapping_file_or_a_comment(self):
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the thing (#976)")
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}, BATCH]
        mate = {**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}
        self.assertIsNone(self.mate_io([]).landed_lead(mate))
        self.assertIsNone(self.mate_io(refused).landed_lead({**issue(974, "Files area: scripts/lib/cmd_land.py"), "comments": 1}))
        self.assertIsNone(self.mate_io(refused).landed_lead(issue(974, "Files area: scripts/lib/cmd_drain.py")))

    def test_a_story_with_its_own_commit_on_main_is_not_a_mate(self):
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the thing (#976)")
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the story (#974)")
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}, BATCH]
        self.assertIsNone(self.mate_io(refused).landed_lead({**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}))

    def test_a_coincidental_touch_is_no_lead_and_the_batch_commit_is_named_over_a_newer_touch(self):
        """#1084: with no batch comment a touched file blocks nothing, and with one the batch commit is named, not the newest touch."""
        refused = {"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}
        mate = {**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}
        self.commit_file("scripts/lib/cmd_drain.py", "Batch work (#976)")
        batch = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.commit_file("scripts/lib/cmd_drain.py", "Later touch (#999)")
        self.assertIsNone(self.mate_io([refused]).landed_lead(mate))
        self.assertEqual(batch, self.mate_io([refused, BATCH]).landed_lead(mate)[0])

    def test_a_commit_already_named_in_a_not_built_comment_gets_no_second_comment(self):
        io = self.mate_io([{"body": "Not built: commit abcdef123456 (x) is the batch session commit"}])
        self.assertTrue(io.told(974, "abcdef1234567890"))
        self.assertFalse(io.told(974, "0123456789abcdef"))
        fake = FakeIo([issue(974)])
        fake.leads[974], fake.toldof = ("abcdef1234567890", "x (#976)"), {(974, "abcdef1234567890")}
        self.assertEqual((False, 0), cmd_drain._work_story(fake, issue(974), state()))
        self.assertEqual([], fake.comments)

    def test_head_that_names_the_story_and_sits_on_the_default_branch_is_landed(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertTrue(self.io.landed(self.repo, 7))
        self.assertFalse(self.io.landed(self.repo, 8))
        self.assertEqual(self.io.commits(self.repo), 0)

    def test_head_ahead_of_the_default_branch_is_not_landed(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        self.assertFalse(self.io.landed(self.repo, 7))
        self.assertEqual(self.io.commits(self.repo), 1)

    def test_a_commit_on_the_default_branch_counts_as_landed_when_the_worktree_is_gone(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertTrue(self.io.landed(Path("/no/such/worktree"), 7))
        self.assertFalse(self.io.landed(Path("/no/such/worktree"), 70))

    def test_close_by_script_logs_the_commit_and_gives_the_gate_a_run_output_line(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        calls, real_run = [], subprocess.run

        def backlog_scripts_only(args, **kwargs):
            if len(args) > 1 and str(args[1]).endswith(("log_action.py", "complete_story.py")):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_run(args, **kwargs)

        with mock.patch.object(cmd_drain.subprocess, "run", backlog_scripts_only):
            closed, reason = self.io.close_by_script(self.repo, 7, "RESULT pushed abc1234")
        self.assertTrue(closed, reason)
        logged = next(c for c in calls if str(c[1]).endswith("log_action.py"))
        self.assertEqual(sha, logged[logged.index("--commit") + 1])
        done = next(c for c in calls if str(c[1]).endswith("complete_story.py"))
        self.assertIn("\nRun output:\nRESULT pushed abc1234", done[done.index("--evidence") + 1])

    def test_keep_open_reopens_a_closed_story_and_queues_its_card_back_to_ready(self):
        calls, queued = [], []
        def gh(args):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "closed\n" if "--jq" in args else "", "")
        cfg = {"repoOwner": "o"}
        with mock.patch.object(cmd_drain.cmd_dispatch, "gh", gh), mock.patch.object(cmd_drain, "backlog_config", lambda repo: cfg), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: queued.extend(fn([])[1])):
            self.io.keep_open(9, "claude exited 1")
        self.assertTrue(any("PATCH" in c and "state=open" in c for c in calls))
        self.assertTrue(any("claude exited 1" in " ".join(c) for c in calls))
        self.assertEqual([{"cfg": cfg, "issues": [{"number": 9, "fields": {"status": "Ready"}}]}], queued)

    def test_release_drops_the_local_claim(self):
        cmd_drain.cmd_dispatch._local_claim("o/r", 7, cmd_drain.time.time(), write="drain")
        with mock.patch.object(cmd_drain.cmd_dispatch.gh_budget, "refusal", return_value="held"):
            self.io.release(7)
        self.assertEqual(cmd_drain.cmd_dispatch._local_claim("o/r", 7, cmd_drain.time.time()), "")


class Held(FakeIo):
    """A FakeIo whose builders wait on a gate, so a stop finds every story still in flight (#1076)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def build(self, i, wt, note):
        self.gate.wait(5)
        return super().build(i, wt, note)


class StoppedRun(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_stop_releases_the_stories_in_flight_and_returns_them_to_ready(self):
        """#1076: Ctrl-C or SIGTERM releases the claim on every story the run was building and does not wait for their builders."""
        io = Held([issue(1), issue(2)], cap=2)
        self.addCleanup(io.gate.set)
        with mock.patch.object(cmd_drain, "wait", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            cmd_drain.drain(io, state(), sleep=lambda s: None, say=lambda t: None)
        self.assertEqual(([1, 2], [1, 2]), (sorted(io.kept), sorted(io.released)))

    def test_sigterm_releases_the_run_lock_and_the_handler_is_put_back(self):
        """#1076: SIGTERM raises inside the run, so the lock goes and the process ends with 130 instead of being killed mid-claim."""
        def stopped(io, st, sleep=None):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)  # the handler raises before this returns
            return 0

        ended = []
        previous = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x")), mock.patch.object(cmd_drain, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(cmd_drain.cmd_dispatch, "origin_slug", return_value="o/r"), mock.patch.object(cmd_drain, "drain", side_effect=stopped):
            code, _ = quiet(cmd_drain.command_drain, ["r"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual([130], ended)
        self.assertFalse(run_lock.path("o/r").exists())
        self.assertEqual(previous, signal.getsignal(signal.SIGTERM))

    def test_sighup_releases_the_run_lock_and_restores_the_handler(self):
        """#1141: closing the terminal tab follows the same cleanup path as SIGTERM."""
        def stopped(io, st, sleep=None):
            os.kill(os.getpid(), signal.SIGHUP)
            time.sleep(5)
            return 0

        previous = signal.getsignal(signal.SIGHUP)
        ended = []
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x")), mock.patch.object(cmd_drain, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(cmd_drain.cmd_dispatch, "origin_slug", return_value="o/r"), mock.patch.object(cmd_drain, "drain", side_effect=stopped):
            code, _ = quiet(cmd_drain.command_drain, ["r"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual([130], ended)
        self.assertFalse(run_lock.path("o/r").exists())
        self.assertEqual(previous, signal.getsignal(signal.SIGHUP))

    def test_a_new_run_releases_the_local_claims_no_live_run_holds_and_leaves_other_repos_alone(self):
        """#1076: a claim a stopped run left behind is released when the next run takes the lock, so the story is eligible in its normal order."""
        now = time.time()
        cmd_drain.cmd_dispatch._local_claim("o/r", 7, now, write="drain")
        cmd_drain.cmd_dispatch._local_claim("o/s", 8, now, write="drain")
        io = FakeIo([])
        out = []
        with mock.patch.object(cmd_drain, "status_page", return_value=""):
            self.assertTrue(cmd_drain.take_run(io, "o/r", "drain r", say=out.append))
        self.assertEqual([7], io.released)
        self.assertIn("Released the claims no run holds: #7", out[-1])
        self.assertEqual("held by drain", cmd_drain.cmd_dispatch._local_claim("o/s", 8, now))

    def test_a_finished_run_returns_its_code_without_ending_the_process(self):
        """#1076: only a stopped run ends the process, so a run that finishes returns to its caller."""
        ended = []
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x")), mock.patch.object(cmd_drain, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(cmd_drain.cmd_dispatch, "origin_slug", return_value="o/r"), mock.patch.object(cmd_drain, "drain", return_value=0):
            code, _ = quiet(cmd_drain.command_drain, ["r"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual((0, []), (code, ended))


class CloseByScript(unittest.TestCase):
    def test_a_refused_close_leaves_the_story_open_with_one_comment_naming_the_gate(self):
        io = FakeIo([issue(1)])
        io.refuse_close = "complete_story: #1 not completed: the evidence holds no run output."
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}})
        self.assertFalse(closed)
        self.assertEqual([], io.closed)
        self.assertEqual([1], io.kept)
        comments = [body for n, body in io.comments if n == 1]
        self.assertEqual(1, len(comments))
        self.assertIn("no run output", comments[0])

    def test_a_landed_story_closes_by_script_without_a_second_session(self):
        io = FakeIo([issue(1)])
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}})
        self.assertTrue(closed)
        self.assertEqual([1], io.closed)
        self.assertEqual(1, io.started.count(1))


class OncePerPassCase(unittest.TestCase):
    def test_the_board_is_read_again_after_the_wait_for_a_free_builder(self):
        io = FakeIo([issue(1)], cap=[0, 0, 1])
        reads, sleeps = [], []
        listed = io.list_open
        io.list_open = lambda: (reads.append(1), listed())[1]
        cmd_drain.drain(io, state(), sleep=sleeps.append, say=lambda t: None)
        self.assertEqual([300], sleeps)
        self.assertEqual([1], io.started)
        self.assertEqual(3, len(reads))  # the start, after the wait, after the story finished

    def test_a_board_read_drops_the_kept_blockers_but_not_the_comments(self):
        io = cmd_drain.Io(Path("/repo"), "o/r", runner=lambda args: mock.Mock(returncode=0, stdout="[]", stderr=""))
        io.memo.get("blockers", {"number": 5}, lambda: [3])
        io.memo.get("comments", {"number": 5}, lambda: ["c"])
        with mock.patch.object(cmd_drain, "fetch_open", return_value=[]), mock.patch.object(cmd_drain, "costed", side_effect=lambda s, c, call: call()), mock.patch.object(io, "board_cards", return_value={}):
            io.list_open()
        self.assertEqual([4], io.memo.get("blockers", {"number": 5}, lambda: [4]))
        self.assertEqual(["c"], io.memo.get("comments", {"number": 5}, lambda: ["new"]))

    def test_the_board_is_read_at_the_start_and_again_only_after_a_story_finishes(self):
        io = FakeIo([issue(1), issue(2)], cap=1)
        reads = []
        listed = io.list_open
        io.list_open = lambda: (reads.append(1), listed())[1]
        drain_io = io
        cmd_drain.drain(drain_io, state(), sleep=lambda s: None, say=lambda t: None)
        self.assertEqual([1, 2], io.started)
        self.assertEqual(3, len(reads))  # the start, then once after each story finished

    def test_io_reads_an_unchanged_story_comments_and_blockers_once(self):
        calls = []
        def runner(args):
            calls.append(args[1])
            return mock.Mock(returncode=0, stdout="[]", stderr="")
        io = cmd_drain.Io(Path("/repo"), "o/r", runner=runner)
        story = {"number": 5, "updated_at": "t", "comments": 1, "issue_dependencies_summary": {"blocked_by": 1}}
        with mock.patch.object(cmd_drain.cmd_dispatch, "live_claim", return_value=""):
            for _ in range(3):
                io.claimed(story), io.blockers(story)
        self.assertEqual(2, len(calls))

    def test_the_drain_calls_are_logged_under_their_own_session_key(self):
        home = temp_dir(self)
        readings = iter([{"remaining": 4000, "reset": 0}, {"remaining": 3990, "reset": 0}])
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_GH_POINTS_FLOOR": "0"}), \
                mock.patch.object(cmd_drain.gh_budget, "points_reading", side_effect=lambda *a, **k: next(readings)):
            self.assertEqual("ok", cmd_drain.costed("drain:o/r", "gh api repos/o/r/issues", lambda: "ok"))
            rows = cmd_drain.gh_budget._read_rows(time.time(), 3600)
            self.assertIn("drain:o/r", [r["session"] for r in rows])


if __name__ == "__main__":
    unittest.main()
