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

from _support import REPO_ROOT, git, git_env, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain, run_lock  # noqa: E402


def issue(n, body="", labels=(), title=None, status="Ready", size="S"):
    """A story Ready on the board and sized, with a Files area of its own unless the body names one (#1014)."""
    if "Files area:" not in body:
        body = f"{body}\nFiles area: scripts/story_{n}.py".lstrip()
    return {"number": n, "title": title or f"Story {n}", "body": body, "labels": [{"name": l} for l in labels], "comments": 0, "status": status, "size": size}


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

    def add_files_area(self, i):
        self.asked = getattr(self, "asked", []) + [i["number"]]
        if i["number"] not in self.found:
            return False
        i["body"] += "\nFiles area: " + self.found[i["number"]]
        return True

    found = {}  # story number -> the Files area the model names for it (#1316)
    def landed_lead(self, i): return self.leads.get(i["number"])
    def staged(self): return False
    def stopped(self, n, reason): self.stops_logged = getattr(self, "stops_logged", []) + [(n, reason)]

    def blockers(self, i):
        """The blockers of a story that are still open, as GitHub's dependency link would name them."""
        return [b for b in self.deps.get(i["number"], []) if b not in self.closed]

    def list_open(self):
        return [i for i in self.issues if i["number"] not in self.closed]

    def claimed(self, i): return i["number"] in self.claims
    def capacity(self):
        return self.cap.pop(0) if isinstance(self.cap, list) and len(self.cap) > 1 else (self.cap[0] if isinstance(self.cap, list) else self.cap)
    def limit(self): return 4
    def claim(self, n, size=""): pass
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

    def test_orders_p0_first_and_skips_epics_claimed_and_owner_gated(self):
        io = FakeIo([issue(1, "Priority: P2"), issue(2, "Priority: P0"), issue(3, "Work type: Epic"), issue(4, labels=["owner-gate"]), issue(5), issue(6, "Priority: P1")], cap=1)
        io.claims.add(5)
        code, out, st = self.run_drain(io)
        self.assertEqual(io.started, [2, 6, 1])
        self.assertEqual(io.closed, [2, 6, 1])
        self.assertIn("Drain done: 3 stories closed", out)
        self.assertEqual(code, 0)

    def test_never_two_builders_on_the_same_files(self):
        io = FakeIo([issue(1, "Files area: scripts/lib/cmd_drain.py"), issue(2, "Files area: scripts/lib/cmd_drain.py"), issue(3, "Files area: scripts/lib/cmd_land.py")], cap=3)
        self.run_drain(io)
        self.assertEqual(sorted(io.closed), [1, 2, 3])
        for active in io.peak_overlap:
            self.assertFalse({1, 2} <= active)

    def test_a_folder_and_a_file_inside_it_overlap_through_the_one_rule(self):
        io = FakeIo([issue(1, "Files area: scripts/lib"), issue(2, "Files area: scripts/lib/cmd_drain.py")], cap=2)
        self.run_drain(io)
        self.assertEqual(sorted(io.closed), [1, 2])
        for active in io.peak_overlap:
            self.assertFalse({1, 2} <= active)

    def test_only_ready_sized_stories_with_a_files_area_are_built_and_each_skip_is_named_once(self):
        io = FakeIo([issue(1, status="Backlog"), issue(2, size=""), {**issue(3), "body": "Priority: P0"}, issue(4)], cap=4)
        code, out, _ = self.run_drain(io)
        self.assertEqual(io.started, [4])
        self.assertIn("Skipped #1: its board Status is Backlog, not Ready.", out)
        self.assertIn("Skipped #2: it has no Size on the board.", out)
        self.assertIn("Skipped #3: it names no Files area and none could be found.", out)
        self.assertEqual([3], io.asked)  # only the Ready, sized story with no area is asked about (#1316)
        self.assertEqual(1, out.count("Skipped #1:"))
        self.assertEqual(code, 0)

    def test_a_ready_story_with_no_files_area_gets_one_and_builds_in_the_same_run(self):
        """#1316"""
        io = FakeIo([{**issue(1), "body": "Priority: P1"}], cap=1)
        io.found = {1: "scripts/lib/cmd_drain.py"}
        code, out, _ = self.run_drain(io)
        self.assertEqual([1], io.started)
        self.assertEqual([1], io.asked)
        self.assertNotIn("Skipped", out)

    def test_add_files_area_edits_the_body_comments_and_refuses_an_untracked_file(self):
        """#1316"""
        repo = temp_dir(self)
        git(repo, "init", "-q")
        (repo / "a.py").write_text("x")
        git(repo, "add", "a.py")
        calls = []
        io = cmd_drain.Io(repo, "o/r", runner=lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
        for text, ok in (("Files area: a.py", True), ("Files area: b.py", False), ("Files area:", False), ("Files area: b.py\nCreates: b.py", True)):
            calls.clear()
            story = {"number": 7, "title": "t", "body": "Creates: b.py" if "Creates" in text else "As the owner"}
            with mock.patch.object(cmd_drain.model, "run_cli", return_value={"code": 0, "text": text}) as ran:
                self.assertEqual(ok, io.add_files_area(story), text)
            self.assertEqual("haiku", ran.call_args.kwargs["model"])
            self.assertEqual(2 if ok else 0, len(calls))  # the body edit, then the comment
            self.assertEqual(ok, "Files area:" in story["body"])
        with mock.patch.object(cmd_drain.model, "run_cli", side_effect=cmd_drain.model.ModelError("no")):
            self.assertFalse(io.add_files_area({"number": 8, "body": ""}))

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

    def test_a_usage_limit_starts_no_new_builder_and_releases_the_story_unblocked(self):  # #1299
        limit = {"done": False, "usage_limit": True, "reason": "Claude usage limit reached: claude exited 1"}
        io = FakeIo([issue(1), issue(2)], cap=1, builds={1: [limit]})
        code, out, st = self.run_drain(io)
        self.assertEqual((io.started, io.kept, io.released, st["blocked"], st["sessions"]), ([1], [1], [1], [], 1))
        self.assertIn("usage limit", io.comments[0][1])
        self.assertIn("Drain stopped for the usage limit", out)

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
                                                                                                             return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch("lib.cmd_status.write_digest"):
            quiet(cmd_drain.command_drain, ["r", "--foreground"], factory, lambda s: None)
            quiet(cmd_drain.command_drain, ["r", "--parallel", "2", "--foreground"], factory, lambda s: None)
            code, _ = quiet(cmd_drain.command_drain, ["r", "--parallel", "0", "--foreground"], factory, lambda s: None)
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

    def test_an_l_or_xl_story_is_skipped_for_splitting_and_the_rest_run(self):
        """#1307: a large story is split into S and M stories before it costs anything."""
        for size in ("L", "XL"):
            self.assertIn("needs splitting into S and M stories", cmd_drain.skip_reason(issue(1, size=size)))
        for size in ("XS", "S", "M"):
            self.assertEqual("", cmd_drain.skip_reason(issue(2, size=size)))
        io = FakeIo([issue(1, size="XL"), issue(2)], cap=4)
        _, out, _ = self.run_drain(io)
        self.assertEqual([2], io.started)
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

    def test_a_refused_push_starts_no_second_builder_and_says_why(self):
        """#1296: a push the repo refused is not the builder's to fix, so the story stops after one build with the push error."""
        io = FakeIo([issue(1)], land_ok=False)
        io.land = lambda wt, n: (False, "RESULT push-failed")
        _, _, st = self.run_drain(io)
        self.assertEqual(io.started, [1])
        self.assertEqual(st["blocked"], [1])
        self.assertIn("push-failed", io.comments[-1][1])

    def test_a_policy_stopped_builder_is_not_restarted_and_the_owner_hears_once(self):
        stop = {"rule": "triggers.deleteFiles", "gate": "Owner identifiers", "finding": "scripts/lib/x.py:4 owner identifier", "file": "scripts/lib/x.py"}
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
        rows += [f"2026-11-23T16:{m:02d}:00Z\tOliverCode-1012\tpolicy\task triggers.deleteFiles\n" for m in range(19, 27)]
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
        stop = {"rule": "triggers.deleteFiles", "gate": "Owner identifiers", "finding": "", "file": ""}
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

    def hold_clock(self, io, holds):
        """Patch the hold: `holds` is the list of epoch offsets blocked_until returns in turn (0 = free). Returns the sleeps and logged rows."""
        naps, rows = [], []
        offsets = list(holds)
        def blocked(resource=""):
            off = offsets.pop(0) if len(offsets) > 1 else offsets[0]
            return time.time() + off if off else 0.0
        return naps, rows, blocked

    def test_a_hold_before_the_board_is_read_waits_for_the_reset_then_builds(self):  # #1314
        io = FakeIo([issue(1)])
        naps, rows, blocked = self.hold_clock(io, [600, 0])
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.gh_budget, "replay") as replay, \
                mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append((a[2], k.get("reason", "")))):
            code, out = quiet(cmd_drain.drain, io, state(), sleep=naps.append)
        self.assertEqual((code, io.started, [r[0] for r in rows if r[0] == "waiting"]), (0, [1], ["waiting"]))
        self.assertTrue(590 < naps[0] < 620)
        replay.assert_called_once()

    def test_a_hold_that_starts_mid_run_lets_builders_finish_then_waits(self):  # #1314
        io = FakeIo([issue(1), issue(2)], cap=1)
        naps, rows, blocked = self.hold_clock(io, [0, 600, 0])
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.gh_budget, "replay"), \
                mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append((a[2], k.get("reason", "")))):
            code, out = quiet(cmd_drain.drain, io, state(), sleep=naps.append)
        self.assertEqual((code, sorted(io.started), len(naps)), (0, [1, 2], 1))

    def test_a_hold_still_on_after_the_wait_stops_the_run_and_names_it(self):  # #1314
        io = FakeIo([issue(1)])
        naps, rows, blocked = self.hold_clock(io, [600])
        st = state()
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.gh_budget, "replay"), \
                mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append((a[2], k.get("reason", "")))):
            code, out = quiet(cmd_drain.drain, io, st, sleep=naps.append)
        self.assertEqual((code, io.started, len(naps), [r[0] for r in rows]), (1, [], 1, ["waiting", "stopped"]))
        self.assertIn("still on after the reset", st["held"])

    def test_no_hold_means_no_waiting_row(self):  # #1314
        io = FakeIo([issue(1)])
        naps, rows, blocked = self.hold_clock(io, [0])
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append(a[2])):
            quiet(cmd_drain.drain, io, state(), sleep=naps.append)
        self.assertEqual((naps, "waiting" in rows), ([], False))

    def test_unreadable_board_stops(self):
        io = FakeIo([])
        io.list_open = lambda: None
        code, out, _ = self.run_drain(io)
        self.assertEqual(code, 1)

    def test_a_board_rest_cannot_read_stops_the_drain_with_that_reason_and_one_stopped_row(self):  # #1310
        io = FakeIo([])
        io.unread = "the board could not be read over REST"
        io.list_open = lambda: None
        rows = []
        with mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append((a[2], k.get("reason", "")))):
            code, out = quiet(cmd_drain.drain, io, state())
        self.assertEqual((code, rows), (1, [("stopped", io.unread)]))
        self.assertIn("the board could not be read over REST", out)

    def test_board_cards_keeps_the_reason_the_board_read_stopped_with(self):  # #1310
        io = cmd_drain.Io.__new__(cmd_drain.Io)
        io.repo = Path("/repo")
        import check_board_hygiene
        with mock.patch.object(cmd_drain, "backlog_config", return_value={}), \
                mock.patch.object(check_board_hygiene, "load_items", side_effect=SystemExit("the board could not be read over REST")):
            self.assertIsNone(io.board_cards())
        self.assertEqual("the board could not be read over REST", io.unread)

    def test_command_refuses_bad_arguments(self):
        self.assertEqual(quiet(cmd_drain.command_drain, [])[0], 2)
        self.assertEqual(quiet(cmd_drain.command_drain, ["/nonexistent-repo-xyz"])[0], 1)

    def test_a_bare_repo_name_resolves_under_repo_root_from_any_checkout(self):
        """#1298: a checkout outside repoRoot still finds `tesknota` under repoRoot."""
        root = temp_dir(self)
        repo = Path(root) / "tesknota"
        (repo / "docs").mkdir(parents=True)
        (repo / "docs" / "backlog-config.json").write_text("{}")
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(root=Path(root))), \
                mock.patch.object(cmd_drain, "OC_ROOT", Path(root) / "_worktrees" / "oc-staging"):
            self.assertEqual(repo.resolve(), cmd_drain.resolve_repo("tesknota"))

    def test_a_drain_of_the_engine_repository_refuses_and_a_scratch_copy_does_not(self):
        """#1278, #1293: any OliverCode checkout is refused unless this machine's settings name an engineBranch."""
        code, out = quiet(cmd_drain.command_drain, [str(cmd_drain.OC_ROOT)])
        self.assertEqual(1, code)
        self.assertIn("Engine changes are the owner's", out)
        self.assertFalse(cmd_drain.cmd_dispatch.is_engine(temp_dir(self)))
        self.assertEqual("main", cmd_drain.agent_loop.default_branch(cmd_drain.OC_ROOT))

    def test_the_owners_engine_branch_allows_the_build_and_lands_it_on_staging(self):
        settings = temp_dir(self) / "olivercode.local.json"
        settings.write_text('{"engineBranch": "staging"}')
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(settings)}):
            self.assertFalse(cmd_drain.cmd_dispatch.is_engine(cmd_drain.OC_ROOT))
            self.assertEqual("staging", cmd_drain.agent_loop.default_branch(cmd_drain.OC_ROOT))
            self.assertNotEqual("staging", cmd_drain.agent_loop.default_branch(temp_dir(self)))


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

    def test_the_claimed_row_and_each_round_row_carry_the_board_size(self):
        """#1301: the claim registers the story's size, so its claimed row and its round rows carry it."""
        self.addCleanup(cmd_drain.agent_loop.STORY_SIZE.pop, "story-7", None)
        self.io.claim(7, "XS")
        cmd_drain.agent_loop.log_round("story-7", 1, "haiku", {})
        rows = [json.loads(l) for l in (Path(os.environ["OLIVERCODE_HOME"]) / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual([("claimed", "XS"), (None, "XS")], [(r.get("stage"), r.get("size")) for r in rows])

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
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}]
        lead = self.mate_io(refused).landed_lead(mate)
        self.assertEqual("Fix the thing (#976)", lead[1])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), lead[0])

    def test_a_story_is_built_as_before_without_a_refused_close_an_overlapping_file_or_a_comment(self):
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the thing (#976)")
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}]
        mate = {**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}
        self.assertIsNone(self.mate_io([]).landed_lead(mate))
        self.assertIsNone(self.mate_io(refused).landed_lead({**issue(974, "Files area: scripts/lib/cmd_land.py"), "comments": 1}))
        self.assertIsNone(self.mate_io(refused).landed_lead(issue(974, "Files area: scripts/lib/cmd_drain.py")))

    def test_a_story_with_its_own_commit_on_main_is_not_a_mate(self):
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the thing (#976)")
        self.commit_file("scripts/lib/cmd_drain.py", "Fix the story (#974)")
        refused = [{"body": "Close refused by complete_story.py: no commit for (#974) is on origin/main"}]
        self.assertIsNone(self.mate_io(refused).landed_lead({**issue(974, "Files area: scripts/lib/cmd_drain.py"), "comments": 1}))

    def test_head_that_names_the_story_and_sits_on_the_default_branch_is_landed(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertTrue(self.io.landed(self.repo, 7))
        self.assertFalse(self.io.landed(self.repo, 8))
        self.assertEqual(self.io.commits(self.repo), 0)

    def test_a_commit_made_before_the_claim_is_not_landed_and_one_after_it_is(self):
        """#1306: an older commit that names the story does not close it; a commit made after the claim does."""
        subprocess.run(["git", "-C", str(self.repo), "commit", "--allow-empty", "-qm", "Part of the thing (#7)"],
                       env=git_env(GIT_COMMITTER_DATE="2020-01-01T00:00:00Z"), check=True, capture_output=True)
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.io.claim_start[7] = time.time()
        self.assertFalse(self.io.landed(self.repo, 7))
        self.io.claim_start[7] = time.time() - 3600
        git(self.repo, "commit", "--allow-empty", "-qm", "Rest of the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertTrue(self.io.landed(self.repo, 7))

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

    def test_each_stage_of_a_story_appends_a_row_to_the_run_log_with_the_story_id_the_rounds_use(self):
        """#1291: claimed, building, landing, landed and stopped come from the real Io, one row each."""
        def rows():
            return [json.loads(l) for l in (Path(os.environ["OLIVERCODE_HOME"]) / "run-log.jsonl").read_text().splitlines()]
        with mock.patch.object(cmd_drain.gh_budget, "refusal", return_value="held"), mock.patch.object(cmd_drain, "backlog_config", lambda repo: {}), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: None), mock.patch.object(cmd_drain.cmd_dispatch, "gh", lambda a: subprocess.CompletedProcess(a, 0, "", "")):
            self.io.claim(7)
            with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as loop:
                self.io.build(issue(7, "Do it."), Path("/wt/7"), "")
            self.assertEqual(self.repo.name, loop.call_args.kwargs["repo"])
            with mock.patch.object(cmd_drain.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                self.io.land(Path("/wt/7"), 7)
            self.io.comment(7, "Drain blocked: validation failed.")
            self.io.keep_open(7)
        stages = [(r["story"], r["repo"], r["stage"]) for r in rows()]
        self.assertEqual([("story-7", self.repo.name, s) for s in ("claimed", "building", "landing", "stopped")], stages)
        self.assertEqual("Drain blocked: validation failed.", rows()[-1]["reason"])

    def test_a_close_that_succeeds_appends_the_landed_row_and_a_refused_close_does_not(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "Fix the thing (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        real_run = subprocess.run
        for code, expected in ((1, []), (0, ["landed"])):
            def scripts(args, **kwargs):
                return subprocess.CompletedProcess(args, code if str(args[1]).endswith("complete_story.py") else 0, "", "") if len(args) > 1 and str(args[1]).endswith(("log_action.py", "complete_story.py")) else real_run(args, **kwargs)
            with mock.patch.object(cmd_drain.subprocess, "run", scripts):
                self.io.close_by_script(self.repo, 7, "pushed")
            log = Path(os.environ["OLIVERCODE_HOME"]) / "run-log.jsonl"
            self.assertEqual(expected, [json.loads(l)["stage"] for l in log.read_text().splitlines()] if log.exists() else [])

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
        mock.patch("lib.cmd_status.write_digest").start()
        self.addCleanup(mock.patch.stopall)

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
            code, _ = quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual([130], ended)
        self.assertFalse(run_lock.path("o/r").exists())
        self.assertEqual(previous, signal.getsignal(signal.SIGTERM))

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
            code, _ = quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual((0, []), (code, ended))


class DetachedRun(unittest.TestCase):
    """#1276: a drain starts as its own process, logs how it ended and can be watched."""

    def setUp(self):
        home = temp_dir(self)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.home = home
        self.digest = mock.patch("lib.cmd_status.write_digest").start()
        self.addCleanup(mock.patch.stopall)
        for target, value in (("resolve_repo", Path("/x/r")), ("backlog_config", {"repoOwner": "o", "repoName": "r"})):
            p = mock.patch.object(cmd_drain, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(cmd_drain.cmd_dispatch, "origin_slug", return_value="o/r")
        p.start()
        self.addCleanup(p.stop)

    def rows(self):
        return [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]

    def test_a_drain_starts_in_its_own_session_with_a_log_and_returns(self):
        spawned = []
        code, out = quiet(cmd_drain.command_drain, ["r", "--parallel", "2"], spawn=lambda cmd, **kw: spawned.append((cmd, kw)))
        cmd, kw = spawned[0]
        self.assertEqual(0, code)
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(["drain", "r", "--parallel", "2", "--foreground"], cmd[-5:])
        self.assertTrue((self.home / "logs" / "drain-r.log").is_file())
        self.assertIn("olivercode watch r", out)
        self.assertEqual(1, out.count("\n"))

    def test_the_run_end_row_counts_the_stories_landed_and_stopped_and_status_shows_it_with_its_time(self):
        def work(io, st, sleep=None):
            st["closed"] += [1, 2]
            st["blocked"].append(3)
            return 0
        with mock.patch.object(cmd_drain, "drain", side_effect=work):
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        end = self.rows()[-1]
        self.assertEqual(("run-end", 2, 1), (end["stage"], end["landed"], end["stopped"]))
        from lib import cmd_status
        lines = cmd_status.activity(time.time(), {}, self.rows(), False, 0, "")
        self.assertRegex(lines[2], r"^Last run ended \d{4}-\d\d-\d\d \d\d:\d\d UTC: 2 stories landed, 1 stopped\.$")

    def test_a_run_end_rewrites_the_status_digest_for_the_repo_and_a_failed_write_still_ends_the_run(self):
        with mock.patch.object(cmd_drain, "drain", return_value=0):
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        self.assertEqual("o/r", self.digest.call_args.args[0])
        self.digest.side_effect = RuntimeError("no network")
        with mock.patch.object(cmd_drain, "drain", return_value=0):
            code, _ = quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        self.assertEqual(0, code)
        self.assertEqual("run-end", self.rows()[-1]["stage"])

    def test_a_run_end_sends_one_notification_with_the_counts(self):
        def work(io, st, sleep=None):
            st["closed"] += [1, 2]
            st["blocked"].append(3)
            return 0
        with mock.patch.object(cmd_drain, "drain", side_effect=work), mock.patch.object(cmd_drain.subprocess, "run") as run:
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        calls = [c for c in run.call_args_list if c.args and c.args[0][0] == "osascript"]
        self.assertEqual(1, len(calls))
        self.assertIn("2 landed, 1 stopped", calls[0].args[0][2])

    def test_notify_sends_nothing_and_does_not_raise_without_osascript(self):
        with mock.patch.object(cmd_drain.subprocess, "run", side_effect=FileNotFoundError):
            cmd_drain.notify("anything")
        cmd_drain.notify("the suite's guard stands in for osascript")

    def test_watch_prints_each_new_stage_row_and_ends_with_the_run(self):
        from lib import cmd_status
        from lib.agent_loop import log_stage
        log_stage("story-168", "r", "building")  # already in the log before watch starts
        steps = iter([lambda: (log_stage("story-169", "r", "claimed"), log_stage("story-169", "r", "validating")),
                      lambda: (log_stage("story-169", "r", "landed"), log_stage("run-r", "r", "run-end", landed=1, stopped=0))])
        lines = []
        code = cmd_status.command_watch(["r"], sleep=lambda s: next(steps)(), out=lines.append, alive=lambda: True)
        self.assertEqual(0, code)
        self.assertEqual(["#169 in r: claimed", "#169 in r: validating", "#169 landed in under a minute"], lines[:3])
        self.assertTrue(lines[3].endswith("1 story landed, 0 stopped."))

    def test_watch_exits_when_no_drain_holds_the_run_lock_and_leaves_the_drain_alone(self):
        from lib import cmd_status
        lines = []
        with mock.patch.object(cmd_status.run_lock, "active", return_value={}):
            code = cmd_status.command_watch(["r"], sleep=lambda s: None, out=lines.append)
        self.assertEqual((0, ["No drain is running for r."]), (code, lines))


if __name__ == "__main__":
    unittest.main()


class CloseByScript(unittest.TestCase):
    def test_a_refused_close_leaves_the_story_open_with_one_comment_naming_the_gate(self):
        io = FakeIo([issue(1)])
        io.refuse_close = "complete_story: #1 not completed: the evidence holds no run output."
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}, "tokens": 0})
        self.assertFalse(closed)
        self.assertEqual([], io.closed)
        comments = [body for n, body in io.comments if n == 1]
        self.assertEqual(1, len(comments))
        self.assertIn("no run output", comments[0])
        self.assertEqual([(1, io.refuse_close)], io.stops_logged)  # #1291: the refusal is the stopped row's reason, and #1297: only one row
        self.assertEqual([], io.kept)  # keep_open would log a second stopped row

    def test_an_engine_story_on_staging_moves_to_qa_and_stays_open(self):
        io = FakeIo([issue(1)])
        io.staged = lambda: True
        io.parked = []
        io.park_in_qa = io.parked.append
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}, "tokens": 0})
        self.assertFalse(closed)
        self.assertEqual(([1], [], [], [1]), (io.parked, io.closed, io.kept, io.released))

    def test_a_landed_story_closes_by_script_without_a_second_session(self):
        io = FakeIo([issue(1)])
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}, "tokens": 0})
        self.assertTrue(closed)
        self.assertEqual([1], io.closed)
        self.assertEqual(1, io.started.count(1))
