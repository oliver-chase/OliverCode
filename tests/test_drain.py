"""`olivercode drain REPO`: ordering, skips, overlap, the one restart, blocker comment and the summary line. Every effect is injected."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import wait
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, git_env, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain, policy, run_lock  # noqa: E402


def issue(n, body="", labels=(), title=None, status="Ready", size="S"):
    """A story Ready on the board and sized, with a Files area of its own unless the body names one (#1014)."""
    if "Files area:" not in body:
        body = f"{body}\nFiles area: scripts/story_{n}.py".lstrip()
    return {"number": n, "title": title or f"Story {n}", "body": body, "labels": [{"name": l} for l in labels], "comments": 0, "status": status, "size": size}


class FakeIo:
    def __init__(self, issues, cap=2, builds=None, land_ok=True, tokens=10, stops=None):
        self.agent, self.moved, self.released, self.already, self.kept, self.on_main = "drain", [], [], False, [], set()
        self.ghost_land = False
        self.said = {}
        self.refuse_close = ""
        self.slug, self.issues, self.cap, self.builds, self.land_ok, self.tokens = "o/r", list(issues), cap, builds or {}, land_ok, tokens
        self.saved = set()  # stories whose card goes to Backlog (#1328, #1531)
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
    def newly_gated(self, issues): return []
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
    red = []  # the failing line the base check returns on each call, "" once the list is spent (#1431)
    def base_failure(self, fresh=False):
        self.fresh_checks = [*getattr(self, "fresh_checks", []), fresh]
        self.base_checks = getattr(self, "base_checks", 0) + 1
        return self.red.pop(0) if self.red else ""
    ci = []  # the failed CI run each read returns, "" once the list is spent (#1482)
    def ci_failure(self):
        self.ci_reads = getattr(self, "ci_reads", 0) + 1
        return self.ci.pop(0) if self.ci else ""
    def validation(self): return None if self.no_validation else ["bash", "scripts/validate.sh"]
    moves_on_land = False  # True makes each landed story move OliverCode's head (#1480)
    def code_head(self): return f"head{len(self.on_main) if self.moves_on_land else 0}"

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

    def commits(self, wt): return getattr(self, "commit_count", 1)
    def stack(self, items):
        self.stacked = getattr(self, "stacked", []) + [[n for _, n in items]]
        return self.stack_ok
    stack_ok = True
    def land(self, wt, n):
        if self.land_ok and not self.ghost_land:
            self.on_main.add(n)
        return self.land_ok, "RESULT pushed abc1234" if self.land_ok else "RESULT validate-failed"
    def comment(self, n, body): self.comments.append((n, body))
    def close_by_script(self, wt, n, why, stage="landed"):
        if self.refuse_close:
            return False, self.refuse_close
        self.closed.append(n)
        self.moved.append(n)
        return True, ""
    def release(self, n): self.released.append(n)
    def set_card(self, n, fields): self.cards = getattr(self, "cards", []) + [(n, fields)]
    parks = {}  # story number -> the cause its parking comment names (#1348)
    def parked_for(self, n): return self.parks.get(n, "")
    def keep_open(self, n, reason=""): self.kept.append(n)
    def save_work(self, wt, n): return self.saves.get(n, [])
    saves = {}  # story number -> the files its stopped builder's work was saved with (#1328)
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

    def test_a_red_base_builds_only_p0_stories_and_posts_one_notification(self):  # #1431
        io = FakeIo([issue(1, "Priority: P1"), issue(2, "Priority: P0")], cap=1)
        io.red = ["FAIL: tests/test_x.py"] * 3
        with mock.patch.object(cmd_drain, "notify") as notify:
            _, _, st = self.run_drain(io)
        self.assertEqual([2], io.started)
        self.assertEqual([2], st["closed"])
        self.assertEqual("FAIL: tests/test_x.py", st["red"])  # story 1 still waits, so the run-end row says why (#1490)
        notify.assert_called_once()
        self.assertIn("FAIL: tests/test_x.py", notify.call_args.args[0])
        self.assertIn("wait until staging passes", notify.call_args.args[0])

    def test_a_failed_ci_run_builds_only_p0_stories_and_logs_the_run(self):  # #1482
        io = FakeIo([issue(1, "Priority: P1"), issue(2, "Priority: P0")], cap=1)
        io.ci = ["CI run https://ci.test/9 failed"] * 3
        with mock.patch.object(cmd_drain, "notify") as notify:
            _, out, st = self.run_drain(io)
        self.assertEqual([2], io.started)
        self.assertEqual([2], st["closed"])
        self.assertEqual(1, out.count("https://ci.test/9"))
        notify.assert_called_once()

    def test_a_passing_ci_run_restores_the_usual_order_without_a_landing(self):  # #1482
        io = FakeIo([issue(1, "Priority: P1"), issue(2, "Priority: P0")], cap=1, builds={2: [{"done": False, "fatal": True, "reason": "x"}]})
        io.ci = ["CI run https://ci.test/9 failed"]  # failed on the first pick, passed on the next
        with mock.patch.object(cmd_drain, "notify"):
            _, _, st = self.run_drain(io)
        self.assertEqual([2, 1], io.started)
        self.assertEqual([1], st["closed"])

    def test_the_real_ci_read_names_a_failed_run_on_the_default_branch_in_one_call(self):  # #1482
        red = "CI run https://ci.test/9 failed"
        for newest_first, expected in ((("failure", "failure"), red), (("failure", "success"), ""), (("success", "failure"), ""), (("failure",), "")):  # #1492
            calls = []
            reply = json.dumps({"workflow_runs": [{"id": 9 - n, "conclusion": c, "html_url": f"https://ci.test/{9 - n}"} for n, c in enumerate(newest_first)]})
            io = cmd_drain.Io(Path("/repo"), "o/r", runner=lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, reply, ""))
            with mock.patch.object(io, "branch", return_value="staging"):
                self.assertEqual(expected, io.ci_failure())
            self.assertEqual([["api", "repos/o/r/actions/runs?branch=staging&status=completed&per_page=2"]], calls)

    def test_every_priority_builds_again_once_the_base_passes_after_a_landing(self):  # #1431
        io = FakeIo([issue(1, "Priority: P1"), issue(2, "Priority: P0")], cap=1)
        io.red = ["FAIL: gate"]  # red at the start, green on the check after story 2 lands
        with mock.patch.object(cmd_drain, "notify"):
            _, _, st = self.run_drain(io)
        self.assertEqual([2, 1], io.started)
        self.assertEqual([2, 1], st["closed"])
        self.assertNotIn("red", st)

    def test_a_passing_base_builds_every_story_without_a_notification(self):  # #1431
        io = FakeIo([issue(1, "Priority: P1"), issue(2, "Priority: P0")], cap=1)
        with mock.patch.object(cmd_drain, "notify") as notify:
            _, _, st = self.run_drain(io)
        self.assertEqual([2, 1], io.started)
        notify.assert_not_called()

    def test_a_builder_that_commits_frees_its_slot_for_the_next_story_while_the_queue_lands(self):  # #1317
        order = []
        io = FakeIo([issue(1), issue(2), issue(3)], cap=1)
        real_land = io.land
        def slow_land(wt, n):
            for _ in range(200):  # the next builder's thread logs its start a moment after the queue takes the story
                if len(io.started) > 1:
                    break
                time.sleep(0.01)
            order.append(("land", n, list(io.started)))
            return real_land(wt, n)
        io.land = slow_land
        _, _, st = self.run_drain(io)
        self.assertEqual([1, 2, 3], sorted(st["closed"]))
        self.assertIn(2, order[0][2])  # story 2 was building when story 1 was landing

    def test_a_story_whose_files_overlap_a_story_waiting_to_land_does_not_start(self):  # #1317
        io = FakeIo([issue(1, "Files area: scripts/x.py"), issue(2, "Files area: scripts/x.py")], cap=2)
        _, _, st = self.run_drain(io)
        self.assertEqual([1, 2], st["closed"])
        self.assertEqual([1, 2], io.started)
        self.assertEqual([], getattr(io, "stacked", []))

    def test_committed_stories_stack_validate_once_and_land_together(self):  # #1317
        io = FakeIo([issue(1), issue(2), issue(3)], cap=3)
        real_land = io.land
        def land(wt, n):
            for _ in range(200):  # the first land holds the queue until the other builders have started and committed
                if len(io.started) == 3:
                    break
                time.sleep(0.01)
            time.sleep(0.1)
            return real_land(wt, n)
        io.land = land
        _, _, st = self.run_drain(io)
        self.assertEqual([1, 2, 3], sorted(st["closed"]))
        self.assertTrue(io.stacked)  # a batch of two or more stacked, and a lone story never does
        self.assertTrue(all(len(batch) >= 2 for batch in io.stacked))
        self.assertLessEqual(len(io.stacked), 2)  # one validation per batch, not per story
        self.assertEqual(len(io.moved), 3)

    def test_a_committed_story_is_landed_when_github_cannot_be_read_after_it_commits(self):  # #1317
        io = FakeIo([issue(1)], cap=1)
        reads = iter([[issue(1)]])
        io.list_open = lambda: next(reads, None)
        code, _, st = self.run_drain(io)
        self.assertEqual(1, code)
        self.assertEqual([1], st["closed"])
        self.assertEqual([1], io.released)

    def test_a_failed_batch_validation_lands_the_passing_stories_and_returns_only_the_failing_one_to_ready(self):  # #1317, #1515
        io = FakeIo([issue(1), issue(2)], cap=2)
        io.stack_ok = False
        real_land = io.land
        def land(wt, n):
            if n == 2 and not io.on_main & {2} and io.started.count(2) == 1:
                return False, "RESULT validate-failed"
            return real_land(wt, n)
        io.land = land
        gate = threading.Event()
        real_build = io.build
        def build(i, wt, note):
            if i["number"] == 1:
                gate.wait(0.3)
            return real_build(i, wt, note)
        io.build = build
        with mock.patch.object(cmd_drain, "notify") as notify:
            _, _, st = self.run_drain(io)
        self.assertEqual(([1], [2], [1, 2]), (st["closed"], st["blocked"], sorted(io.started)))
        self.assertEqual(([2], [1, 2]), (io.kept, sorted(io.released)))
        self.assertEqual([(2, "Drain blocked: Landing failed: RESULT validate-failed")], io.comments)
        notify.assert_called_once_with("#2 didn't land yet. It'll try again on its own.")

    def test_one_committed_story_lands_with_no_stack(self):  # #1317
        io = FakeIo([issue(1)], cap=1)
        _, _, st = self.run_drain(io)
        self.assertEqual([1], st["closed"])
        self.assertEqual([], getattr(io, "stacked", []))
        self.assertEqual([1], io.released)

    def test_a_story_that_stops_with_saved_work_gets_one_comment_naming_branch_files_and_reason(self):
        """#1328"""
        io = FakeIo([issue(1)], cap=1, builds={1: [{"done": False, "reason": "max_turns"}] * 2})
        io.saves = {1: ["a.py", "b.py"]}
        self.run_drain(io)
        body = "\n".join(b for _, b in io.comments)
        self.assertEqual(1, len(io.comments))
        self.assertIn("story/1", body)
        self.assertIn("a.py, b.py", body)
        self.assertIn("max_turns", body)

    def test_a_story_that_stops_with_a_clean_worktree_keeps_todays_comment(self):
        io = FakeIo([issue(1)], cap=1, builds={1: [{"done": False, "reason": "max_turns"}] * 2})
        self.run_drain(io)
        self.assertTrue(io.comments[0][1].startswith("Drain blocked: the builder crashed or timed out again"))

    def test_orders_p0_first_and_skips_epics_claimed_and_owner_gated(self):
        io = FakeIo([issue(1, "Priority: P2"), issue(2, "Priority: P0"), issue(3, "Work type: Epic"), issue(4, labels=["owner-gate"]), issue(5), issue(6, "Priority: P1")], cap=1)
        io.claims.add(5)
        code, out, st = self.run_drain(io)
        self.assertEqual(io.started, [2, 6, 1])
        self.assertEqual(io.closed, [2, 6, 1])
        self.assertIn("Drain done: 3 stories closed", out)
        self.assertEqual(code, 0)

    def test_only_the_fields_line_or_the_label_marks_an_epic(self):  # #1514
        quoting = ("Scenario: A real epic\n    Given a body reading `Priority: P1. Size: L. Work type: Epic.`\n"
                   "    Work type: Epic\n\nPriority: P1. Size: S. Work type: Story.")
        io = FakeIo([issue(1, quoting), issue(2, "Priority: P1. Size: S. Work type: Epic.\r\n"), issue(3, "Priority: P1 · Size: L · Work type: Epic"),
                     issue(4, labels=["epic"])])
        self.run_drain(io)
        self.assertEqual([1], io.started)

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
        code, out, st = self.run_drain(io)
        self.assertEqual(io.started, [2, 1])
        self.assertIn("Skipped #1: it is blocked by open #2.", out)
        self.assertEqual(({}, {}), (st["skipped"], st["why"]))  # a story that starts later is not reported at the run's end (#1510)

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

    def test_a_stuck_or_backstop_stop_comments_the_reason_returns_the_card_and_starts_no_restart(self):  # #1318, #1515
        for flag, reason in (("stuck", "Stuck: rounds 1 and 2 failed validation the same way, so no further round starts."),
                             ("capped", "Spend $12.10 reached the backstop of $12.00, so no further round starts.")):
            io = FakeIo([issue(1)], builds={1: [{"done": False, flag: True, "reason": reason}]})
            io.saves = {1: ["a.py"]}  # saved work would send the card to Backlog, so none is saved
            io.save_work = lambda wt, n: self.fail("a stuck or capped story saved its work")
            _, _, st = self.run_drain(io)
            self.assertEqual(([1], [1], [1], 1), (io.started, io.kept, st["blocked"], st["sessions"]), flag)
            self.assertEqual([(1, f"Drain stopped: {reason}")], io.comments)

    def test_a_story_whose_rounds_changed_nothing_waits_for_the_owner_with_the_builders_reply(self):  # #1531
        idle = {"done": False, "stuck": True, "idle": True, "reason": "Stuck: rounds 1 and 2 changed nothing.", "summary": "I cannot meet scenario 2."}
        for builds in ([idle], [{"done": False, "reason": "claude exited 1"}, idle]):
            stops = {1: {"rule": "r", "gate": ""}} if len(builds) == 1 else {}  # a policy ask in the same run adds no second comment or line
            io = FakeIo([issue(1)], builds={1: [dict(b) for b in builds]}, stops=stops)
            io.commit_count = 0
            io.save_work = lambda wt, n: self.fail("a story whose rounds changed nothing saved its work")
            with mock.patch.object(cmd_drain, "notify") as notify:
                _, _, st = self.run_drain(io)
            self.assertEqual((len(builds), {1}, [1], [1]), (len(io.started), io.saved, io.kept, st["blocked"]))
            self.assertEqual(1, len(io.comments))
            self.assertTrue(io.comments[0][1].startswith(cmd_drain.IDLE))
            self.assertIn("I cannot meet scenario 2.", io.comments[0][1])
            self.assertEqual([1], [n for n, _ in io.owner])
            notify.assert_called_once_with("#1 needs you. The story says what to do.")

    def test_a_crashed_or_timed_out_builder_restarts_once_on_the_same_worktree_then_lands(self):  # #1515
        for reason in ("claude exited 1 in round 1.", "claude -p ran past 1800 seconds and was stopped."):
            io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": reason}]})
            builds, real = [], io.build
            io.build = lambda i, wt, note: builds.append((wt, note)) or real(i, wt, note)
            _, _, st = self.run_drain(io)
            self.assertEqual([(Path("/wt/1"), ""), (Path("/wt/1"), reason)], builds)
            self.assertEqual(([1], 2, []), (io.closed, st["sessions"], io.comments))

    def test_a_second_crash_comments_the_blocker_starts_no_third_builder_and_moves_on(self):  # #1515
        dead = {"done": False, "reason": "out of budget"}
        io = FakeIo([issue(1, "Priority: P0"), issue(2)], cap=1, builds={1: [dict(dead) for _ in range(3)]})
        _, out, st = self.run_drain(io)
        self.assertEqual(io.started.count(1), 2)
        self.assertEqual(io.closed, [2])
        self.assertEqual([n for n, _ in io.comments if n == 1], [1])
        self.assertIn("out of budget", io.comments[0][1])
        self.assertEqual(st["blocked"], [1])

    def test_a_restarted_builder_that_gets_stuck_stops_with_that_reason(self):  # #1515
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "claude exited 1"}, {"done": False, "stuck": True, "reason": "Stuck: same failure"}]})
        _, _, st = self.run_drain(io)
        self.assertEqual(([1, 1], [1], [(1, "Drain stopped: Stuck: same failure")]), (io.started, st["blocked"], io.comments))

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
        idle = mock.patch.object(cmd_drain.os, "getloadavg", return_value=(0.0, 0.0, 0.0))  # a loaded machine would cap the count (#1487)
        idle.start()
        self.addCleanup(idle.stop)
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
            self.assertIn("needs splitting into S and M stories", cmd_drain.skip_reason(issue(1, f"Size: {size}", size=size)))
        for size in ("XS", "S", "M"):
            self.assertEqual("", cmd_drain.skip_reason(issue(2, f"Size: {size}", size=size)))
        io = FakeIo([issue(1, "Size: XL", size="XL"), issue(2)], cap=4)
        _, out, _ = self.run_drain(io)
        self.assertEqual([2], io.started)
        self.assertIn("Skipped #1", out)

    def test_the_text_size_decides_the_refusal_and_a_mismatch_is_logged_once(self):
        """#1342: the card says XL and the text says M, so the story builds; text L refuses; no Size line falls back to the body length."""
        io = FakeIo([issue(1, "Size: M", size="XL")], cap=4)
        _, out, _ = self.run_drain(io)
        self.assertEqual([1], io.started)
        self.assertEqual(1, out.count("its card says Size XL but its text says M"))
        self.assertIn("needs splitting", cmd_drain.skip_reason(issue(2, "Size: L", size="S")))
        self.assertEqual("", cmd_drain.skip_reason(issue(3, size="XL")))  # a short body with no Size line reads as XS

    def test_a_mismatched_card_is_set_from_the_text_and_a_parked_story_returns_when_its_cause_is_gone(self):
        """#1348: the card follows the text Size; Backlog stories parked for an overlap or a fitting Size go to Ready with one comment; a text Size XL stays."""
        io = FakeIo([issue(1, "Size: S", size="XL"), issue(2, "Size: S", status="Backlog"), issue(3, "Size: XL", status="Backlog")], cap=4)
        io.parks = {2: "overlap", 3: "size"}
        self.run_drain(io)
        self.assertIn((1, {"size": "S"}), io.cards)
        self.assertIn((2, {"status": "Ready"}), io.cards)
        self.assertEqual([2], [n for n, b in io.comments if b.startswith("Back to Ready:")])
        self.assertNotIn((3, {"status": "Ready"}), io.cards)
        self.assertNotIn(3, io.started)

    def test_the_parking_cause_reads_each_comment_in_order(self):
        """#1348: a story parked, returned and parked again reads as parked, and a comment's own blank lines do not split it."""
        def io_for(*bodies):
            out = "".join(json.dumps(b) + "\n" for b in bodies)
            return cmd_drain.Io(Path("/repo"), "o/r", runner=lambda args: subprocess.CompletedProcess(args, 0, out, ""))
        park, back = "#5 shares a.py in its Files area.", "Back to Ready: the drain builds stories that share files one after the other."
        self.assertEqual("overlap", io_for(park, back, park).parked_for(1))
        self.assertEqual("", io_for(park, back).parked_for(1))
        self.assertEqual("size", io_for("Parked.\n\nSize XL is too large for one builder session.").parked_for(1))
        self.assertEqual("", io_for("Size XL is too large for one builder session.\n\nBack to Ready: its text Size S fits one builder.").parked_for(1))

    def test_a_full_machine_waits_for_a_free_builder(self):
        """#1055: no free builder means wait, then start."""
        io = FakeIo([issue(1)], cap=[0, 0, 1])
        naps = []
        quiet(cmd_drain.drain, io, cmd_drain.new_state(), sleep=naps.append)
        self.assertEqual(([1], 1), (io.started, len(naps)))

    def test_a_load_above_twice_the_cores_caps_a_run_at_one_builder(self):
        """#1487: --parallel is capped too, a load of exactly twice the cores is normal, and a full machine stays full."""
        for load, parallel, elsewhere, want in ((16.0, None, 0, 2), (16.1, None, 0, 1), (16.0, 3, 0, 3), (16.1, 3, 0, 1), (16.1, None, 2, 0)):
            with mock.patch.object(cmd_drain.os, "getloadavg", return_value=(load, 0.0, 0.0)), mock.patch.object(cmd_drain.os, "cpu_count", return_value=8), \
                    mock.patch.object(cmd_drain.local_config, "max_builders", return_value=2), \
                    mock.patch.object(cmd_drain.run_lock, "building_elsewhere", return_value=elsewhere):
                self.assertEqual(want, cmd_drain.Io(Path("/nonexistent"), "o/r", parallel=parallel).capacity(), (load, parallel, elsewhere))

    def test_a_heavily_loaded_drain_builds_one_story_at_a_time_until_none_is_left(self):
        """#1487: the load never stops the run, and a normal load fills the limit."""
        for load, most in ((999.0, 1), (0.0, 2)):
            io = FakeIo([issue(1), issue(2), issue(3)])
            io.parallel, io.capacity = 2, lambda: cmd_drain.Io.capacity(io)
            with mock.patch.object(cmd_drain.os, "getloadavg", return_value=(load, 0.0, 0.0)):
                self.run_drain(io)
            self.assertEqual((most, [1, 2, 3]), (max(map(len, io.beats)), sorted(io.closed)), load)

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

    def test_a_failed_reader_stops_the_story_with_its_cause_and_is_never_read_back_as_a_finding(self):  # #1489
        cause = "claude exited 1 in attempt 2, stop reason max_turns."
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reader_failed": cause, "reason": "The reader failed"}]})
        _, _, st = self.run_drain(io)
        self.assertEqual(([1], [1], [1], set()), (io.started, io.kept, st["blocked"], io.on_main))
        self.assertEqual([1], [n for n, _ in io.comments])
        body = io.comments[0][1]
        for part in ("reader failed", "stop reason max_turns", "nothing was pushed"):
            self.assertIn(part, body)
        self.assertNotIn(cmd_drain.HELD, body)
        rows = json.dumps({"body": body, "author_association": "OWNER"})
        reader = cmd_drain.Io(Path("/nonexistent"), "o/r", runner=lambda args: subprocess.CompletedProcess(args, 0, rows, ""))
        self.assertEqual("", reader.held_finding(1))

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
        io.commit_count = 0  # the builder left no commit, so the ask stops it (#1473)
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
        io.commit_count = 0
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            _, out, st = self.run_drain(io)
        self.assertEqual(io.started, [1012])
        self.assertEqual(1, len(io.comments))
        self.assertIn("File: scripts/lib/owner.py", io.comments[0][1])
        self.assertEqual(st["blocked"], [1012])

    def test_a_builder_that_got_past_an_ask_and_committed_is_not_policy_stopped(self):  # #1473
        stop = {"rule": "triggers.deleteFiles", "gate": "", "finding": "", "file": "", "command": "git rm -r old"}
        io = FakeIo([issue(1)], builds={1: [{"done": True}]}, stops={1: stop}, land_ok=False)
        _, out, st = self.run_drain(io)
        self.assertEqual([], io.owner)
        self.assertFalse(any("Stopped by the policy" in c for _, c in io.comments))

    def test_the_logged_ask_names_its_command_and_the_stop_comment_repeats_it(self):  # #1473
        log = temp_dir(self) / "failures.log"
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            start = "2000-01-01T00:00:00Z"
            policy.log_block(policy.Decision("ask", "triggers.deleteFiles", "r"), "OliverCode-9", "git rm -r " + "x" * 200)
            stop = cmd_drain.policy_stop_in("OliverCode-9", start)
        self.assertEqual("triggers.deleteFiles", stop["rule"])
        self.assertEqual(("git rm -r " + "x" * 200)[:120], stop["command"])
        self.assertIn("Command: git rm -r ", cmd_drain.policy_stop_comment(stop))

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

    def test_a_stop_for_rounds_that_changed_nothing_queues_one_owner_line_and_ends_an_earlier_parking(self):  # #1531
        parking = "It shares a.py in its Files area with #2."
        comments = [parking, f"{cmd_drain.IDLE} Stuck.\n\nThe builder's last reply:\n{parking}"]
        io = cmd_drain.Io(Path("/repo"), "o/r", runner=lambda args: subprocess.CompletedProcess(args, 0, "\n".join(map(json.dumps, comments)), ""))
        self.assertEqual("", io.parked_for(7))
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}):
            io.queue_owner(7, {"why": "its builder's rounds changed nothing."})
            io.queue_owner(7, {"why": "its builder's rounds changed nothing."})
            from lib import cmd_owner
            steps = [(i["story"], i["step"]) for i in cmd_owner.items()]
        self.assertEqual([(7, "Story #7 waits on you: its builder's rounds changed nothing.")], steps)

    def test_a_failed_landing_starts_no_restart(self):  # #1515
        io = FakeIo([issue(1)], land_ok=False)
        self.run_drain(io)
        self.assertEqual(io.started, [1])
        self.assertEqual((io.closed, io.kept), ([], [1]))
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

    def test_a_hold_notifies_once_when_the_wait_starts_and_once_when_the_run_quits(self):  # #1325
        io = FakeIo([issue(1)])
        naps, rows, blocked = self.hold_clock(io, [600])
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.gh_budget, "replay"), \
                mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: rows.append((a[2], k.get("reason", "")))), \
                mock.patch.object(cmd_drain, "notify") as notify:
            quiet(cmd_drain.drain, io, state(), sleep=naps.append)
        texts = [c.args[0] for c in notify.call_args_list]
        self.assertEqual(len(texts), 2)
        self.assertIn("Paused for GitHub's limit. Back at about", texts[0])
        self.assertIn("Stopped at GitHub's limit", texts[1])
        self.assertTrue(all(len(t) <= 110 for t in texts))
        self.assertNotIn("still on after the reset it named", texts[1])
        self.assertNotIn("rate-limit", texts[0] + texts[1])

    def test_a_story_that_stops_without_landing_notifies_in_plain_words_without_the_reason(self):  # #1325, #1374
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "review still failing"} for _ in range(4)]})
        io.said[1] = "review still failing"
        with mock.patch.object(cmd_drain, "notify") as notify:
            self.run_drain(io)
        notify.assert_called_once_with("#1 didn't land yet. It'll try again on its own.")

    def test_an_io_with_no_said_map_still_notifies_a_stopped_story(self):  # #1325, dispatch's RunIo has none
        io = FakeIo([issue(1)], builds={1: [{"done": False, "reason": "x"} for _ in range(4)]})
        del io.said
        with mock.patch.object(cmd_drain, "notify") as notify:
            self.run_drain(io)
        self.assertIn("didn't land yet", notify.call_args.args[0])

    def test_a_story_that_lands_sends_no_notification(self):  # #1325
        io = FakeIo([issue(1)])
        with mock.patch.object(cmd_drain, "notify") as notify:
            self.run_drain(io)
        self.assertEqual((io.closed, [c.args[0] for c in notify.call_args_list if "didn't land" in c.args[0] or "Paused" in c.args[0]]), ([1], []))

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
        """#1298: a checkout outside repoRoot still finds `my-repo` under repoRoot."""
        root = temp_dir(self)
        repo = Path(root) / "my-repo"
        (repo / "docs").mkdir(parents=True)
        (repo / "docs" / "backlog-config.json").write_text("{}")
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(root=Path(root))), \
                mock.patch.object(cmd_drain, "OC_ROOT", Path(root) / "_worktrees" / "oc-staging"):
            self.assertEqual(repo.resolve(), cmd_drain.resolve_repo("my-repo"))

    def test_a_bare_repo_name_finds_a_worktree_and_prefers_repo_root(self):
        """#1336: PATH runs a checkout directly under repoRoot, and `oc-staging` sits in repoRoot/_worktrees."""
        root = Path(temp_dir(self))
        made = {}
        for key, rel in (("tree", "_worktrees/oc-staging"), ("top", "oc-staging")):
            made[key] = root / rel
            (made[key] / "docs").mkdir(parents=True)
            (made[key] / "docs" / "backlog-config.json").write_text("{}")
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(root=root)), mock.patch.object(cmd_drain, "OC_ROOT", root / "olivercode"):
            self.assertEqual(made["top"].resolve(), cmd_drain.resolve_repo("oc-staging"))
            (made["top"] / "docs" / "backlog-config.json").unlink()
            self.assertEqual(made["tree"].resolve(), cmd_drain.resolve_repo("oc-staging"))
            self.assertIsNone(cmd_drain.resolve_repo("missing-repo"))

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

    def test_the_base_check_runs_under_worktrees_and_leaves_no_worktree(self):
        """#1433: the check's worktree sits in repoRoot/_worktrees, not the temp folder, and is gone when it ends, passed or failed."""
        git(self.repo, "remote", "add", "origin", str(self.repo))
        root = temp_dir(self)
        seen = []
        for passed, expected in ((True, ""), (False, "boom")):
            def validate(wt):
                seen.append(Path(wt).parent)
                return (0 if passed else 1), "boom"
            self.assertEqual(expected, self.base(validate, root / "_worktrees"))
            self.assertNotIn("-base-", git(self.repo, "worktree", "list").stdout)
        self.assertEqual([root / "_worktrees"] * 2, seen)

    def base(self, validate, folder=None, recorded=False):
        """The base check's result with validation replaced by `validate` and a recorded pass for the tree when `recorded`."""
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(worktrees=folder or temp_dir(self) / "_worktrees")), \
                mock.patch.object(cmd_drain.cmd_land, "prepare_worktree"), \
                mock.patch.object(cmd_drain.agent_loop, "validation_command", return_value=["true"]), \
                mock.patch.object(cmd_drain.validated, "is_validated", return_value=recorded), \
                mock.patch.object(cmd_drain.agent_loop, "validate_code", validate):
            return self.io.base_failure()

    def test_a_tree_with_a_recorded_pass_is_not_validated_again(self):
        """#1436: land's recorded pass for origin's tree answers the base check, and a tree with none is validated once."""
        git(self.repo, "remote", "add", "origin", str(self.repo))
        runs = []
        self.assertEqual("", self.base(lambda wt: runs.append(1) or (1, "boom"), recorded=True))
        self.assertEqual([], runs)
        self.assertEqual("boom", self.base(lambda wt: runs.append(1) or (1, "boom")))
        self.assertEqual([1], runs)

    def test_a_timeout_is_rerun_once_and_two_read_as_unknown(self):
        """#1436: exit 124 is rerun; a pass on the rerun is a pass, two timeouts log one line and build everything, and a real failure still filters."""
        git(self.repo, "remote", "add", "origin", str(self.repo))
        for results, expected, said in (([(124, "slow"), (0, "ok")], "", False), ([(124, "slow"), (124, "slow")], "", True), ([(124, "slow"), (1, "boom")], "boom", False)):
            queue = list(results)
            with mock.patch("builtins.print") as out:
                self.assertEqual(expected, self.base(lambda wt: queue.pop(0)))
            self.assertEqual([], queue)
            self.assertEqual(said, any("timed out twice" in str(c) for c in out.call_args_list))

    def test_the_brief_is_built_by_the_real_rules_without_a_missing_key(self):
        seen = {}
        with mock.patch.object(cmd_drain.agent_loop, "run_loop", lambda brief, wt, name, **kw: seen.update(brief=brief) or {"done": True}):
            self.io.build(issue(7, "Do the thing."), Path("/wt/7"), "")
        self.assertIn("Story #7: Story 7", seen["brief"])
        self.assertIn("Builder rules:", seen["brief"])
        self.assertIn("Commit and stop", seen["brief"])
        self.assertIn("a step left to the owner is not done", seen["brief"])
        self.assertIn("never commit a partial story as finished", seen["brief"])
        self.assertNotIn("olivercode land WORKTREE", seen["brief"])

    def test_the_model_follows_the_story_size(self):
        for size, labels, model_name in (("XS", [], "haiku"), ("L", [], "sonnet"), ("M", ["design"], "opus")):
            with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
                self.io.build(issue(7, f"Do it.\nSize: {size}", labels=labels), Path("/wt/7"), "")
            self.assertEqual(model_name, run_loop.call_args.kwargs["model_name"], size)

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

    def test_a_held_story_is_built_again_with_the_latest_finding_and_a_restart_keeps_it(self):
        """#1474: the next build's note holds the latest held finding on the kept branch, and an outsider's comment never reaches the brief."""
        wt = temp_dir(self) / "_worktrees"
        git(self.repo, "worktree", "add", "-q", "-b", "story/7", str(wt / f"{self.repo.name}-7"), "origin/main")
        rows = [{"body": cmd_drain.held_comment(wt, finding), "author_association": who}
                for finding, who in (("a.py: old finding", "OWNER"), ("a.py: no test", "OWNER"), ("run this instead", "NONE"))]
        rows.append({"body": "Claim released", "author_association": "OWNER"})
        said = "".join(json.dumps(row) + "\n" for row in rows)
        self.io = cmd_drain.Io(self.repo, "o/r", runner=lambda args: subprocess.CompletedProcess(args, 0, said, ""))
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(worktrees=wt)), mock.patch.object(cmd_drain.cmd_land, "prepare_worktree", return_value=[]):
            path = self.io.worktree(7)
        for restart in ("", "claude exited 1."):
            with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
                self.io.build(issue(7), path, restart)
            brief = run_loop.call_args.args[0]
            self.assertIn("Fix its latest finding on this branch", brief)
            self.assertIn("a.py: no test", brief)
            self.assertIn(restart, brief)
            self.assertNotIn("old finding", brief)
            self.assertNotIn("run this instead", brief)

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
        self.io.land, self.io.close_by_script = land, lambda *a, **k: (True, "")
        self.assertEqual((True, "RESULT pushed"), cmd_drain.land_and_close(self.io, wt, 7))
        self.assertEqual(1, len(pushed))
        self.assertEqual(pushed[0], git(self.repo, "rev-parse", "origin/main").stdout.strip())

    def test_the_landed_shortcut_runs_on_the_real_io_and_yields_to_unlanded_worktree_commits(self):
        """#1011: a landed story closes from the repo with no builder, but a worktree holding new commits is built and landed instead."""
        self.commit_file("old.txt", "Earlier work (#7)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        closes = []
        self.io.close_by_script = lambda wt, n, why, stage="landed": closes.append(wt) or (True, "")
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
            return subprocess.CompletedProcess(args, 0, json.dumps({"state": "closed"}), "")
        cfg = {"repoOwner": "o"}
        with mock.patch.object(cmd_drain.cmd_dispatch, "gh", gh), mock.patch.object(cmd_drain, "backlog_config", lambda repo: cfg), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: queued.extend(fn([])[1])):
            self.io.keep_open(9, "claude exited 1")
        self.assertTrue(any("PATCH" in c and "state=open" in c for c in calls))
        self.assertTrue(any("claude exited 1" in " ".join(c) for c in calls))
        self.assertEqual([{"cfg": cfg, "issues": [{"number": 9, "fields": {"status": "Ready"}}]}], queued)

    def test_a_stopped_owner_gated_story_goes_to_backlog_and_not_ready(self):  # #1496
        queued = []
        story = json.dumps({"state": "open", "labels": [{"name": "owner-action"}]})
        with mock.patch.object(cmd_drain.cmd_dispatch, "gh", lambda a: subprocess.CompletedProcess(a, 0, story, "")), mock.patch.object(cmd_drain, "backlog_config", lambda repo: {}), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: queued.extend(fn([])[1])):
            self.io.keep_open(9)
        self.assertEqual("Backlog", queued[0]["issues"][0]["fields"]["status"])

    def test_a_stopped_builders_uncommitted_work_is_committed_and_pushed_to_its_branch(self):
        """#1328: the changes go to story/N by one commit that names the story, and the card then moves to Backlog."""
        remote = scratch_repo(temp_dir(self), bare=True)
        git(self.repo, "remote", "add", "origin", str(remote))
        (self.repo / "half.py").write_text("x = 1\n")
        self.assertEqual(["half.py"], self.io.save_work(self.repo, 7))
        self.assertIn("Partial work from a stopped builder (#7)", git(self.repo, "log", "-1", "--format=%s").stdout)
        self.assertIn("refs/heads/story/7", git(remote, "for-each-ref").stdout)
        self.assertEqual("", git(self.repo, "status", "--porcelain").stdout.strip())
        queued = []
        with mock.patch.object(cmd_drain.cmd_dispatch, "gh", lambda a: subprocess.CompletedProcess(a, 0, "open\n", "")), mock.patch.object(cmd_drain, "backlog_config", lambda repo: {}), \
                mock.patch.object(cmd_drain.cmd_dispatch.batch_project, "with_queue", lambda fn: queued.extend(fn([])[1])):
            self.io.keep_open(7)
        self.assertEqual("Backlog", queued[0]["issues"][0]["fields"]["status"])

    def test_a_clean_worktree_makes_no_commit(self):
        before = git(self.repo, "rev-parse", "HEAD").stdout
        self.assertEqual([], self.io.save_work(self.repo, 7))
        self.assertEqual(before, git(self.repo, "rev-parse", "HEAD").stdout)
        self.assertNotIn(7, self.io.saved)

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

    def test_a_refused_landing_appends_a_stopped_row_with_its_reason_and_is_never_left_as_landing(self):
        """#1486: a land that ends with RESULT weakened-test shows as stopped at once, with the refusal as its reason."""
        refused = subprocess.CompletedProcess([], 1, "RESULT weakened-test \n", "")
        with mock.patch.object(cmd_drain.subprocess, "run", return_value=refused):
            landed, _ = self.io.land(Path("/wt/7"), 7)
        last = [json.loads(l) for l in (Path(os.environ["OLIVERCODE_HOME"]) / "run-log.jsonl").read_text().splitlines()][-1]
        self.assertFalse(landed)
        self.assertEqual(("story-7", "stopped", "Landing refused: weakened-test"), (last["story"], last["stage"], last["reason"]))

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
        cmd_drain.cmd_dispatch._local_claim("o/r", 9, now, write="dispatch")
        io = FakeIo([])
        out = []
        with mock.patch.object(cmd_drain, "status_page", return_value=""):
            self.assertTrue(cmd_drain.take_run(io, "o/r", "drain r", say=out.append))
        self.assertEqual([7, 9], io.released)
        self.assertIn("Released the claims no run holds: #7, #9", out[-1])
        self.assertEqual("held by drain", cmd_drain.cmd_dispatch._local_claim("o/s", 8, now))

    def test_a_new_run_leaves_a_chat_sessions_claim_which_counts_as_free_once_stale(self):
        """#1536: only a runner's claim is released, so a story a chat session is building is skipped as claimed until its claim ages out."""
        now = time.time()
        cmd_drain.cmd_dispatch._local_claim("o/r", 7, now, write="238bb789-a732-4d0d-871f-97cec369e8a4")
        io = FakeIo([])
        with mock.patch.object(cmd_drain, "status_page", return_value=""):
            self.assertTrue(cmd_drain.take_run(io, "o/r", "drain r", say=lambda t: None))
        self.assertEqual([], io.released)
        reader = cmd_drain.Io(Path("/x"), "o/r")
        self.assertTrue(reader.claimed({"number": 7}))
        with mock.patch.object(cmd_drain.time, "time", return_value=now + cmd_drain.cmd_dispatch.log_action.CLAIM_HOURS * 3600 + 1):
            self.assertFalse(reader.claimed({"number": 7}))

    def test_a_finished_run_returns_its_code_without_ending_the_process(self):
        """#1076: only a stopped run ends the process, so a run that finishes returns to its caller."""
        ended = []
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x")), mock.patch.object(cmd_drain, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(cmd_drain.cmd_dispatch, "origin_slug", return_value="o/r"), mock.patch.object(cmd_drain, "drain", return_value=0):
            code, _ = quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]), exit_now=ended.append)
        self.assertEqual((0, []), (code, ended))


SHARED = "Files area: scripts/shared.py"
GONE_LINE = "Error: 'queue' is not a valid command. Guide: olivercode guide"


class StaleCode(unittest.TestCase):
    """#1480: a drain runs the code on staging, and stops when its validation calls a command that is gone."""

    def setUp(self):
        self.home = temp_dir(self)
        mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}).start()
        mock.patch("lib.cmd_status.write_digest").start()
        mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x/r")).start()
        mock.patch.object(cmd_drain, "slug_of", return_value="o/r").start()
        self.notify = mock.patch.object(cmd_drain, "notify").start()
        self.addCleanup(mock.patch.stopall)

    def command(self, io, argv):
        spawned = []
        code, out = quiet(cmd_drain.command_drain, argv, lambda repo, slug, parallel=None: io, spawn=lambda cmd, **kw: spawned.append((cmd, run_lock.path("o/r").exists())))
        rows = [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]
        return code, spawned, [r for r in rows if r["stage"] == "restarting"]

    def test_a_moved_head_starts_no_new_story_and_restarts_the_drain_once_with_the_same_flags(self):
        io = FakeIo([issue(1, SHARED), issue(2, SHARED)], cap=1)  # story 2 shares a file, so it cannot start before story 1 lands
        io.moves_on_land = True
        code, spawned, rows = self.command(io, ["r", "--parallel", "1", "--foreground"])
        self.assertEqual((0, [1], [1]), (code, io.started, io.closed))
        self.assertEqual(1, len(spawned))
        cmd, locked = spawned[0]
        self.assertEqual(["drain", "r", "--parallel", "1", "--foreground"], cmd[-5:])
        self.assertEqual(1, cmd.count("--foreground"))
        self.assertFalse(locked)  # the new process can take the run lock
        self.assertEqual(1, len(rows))
        self.assertIn("from head0 to head1", rows[0]["reason"])

    def test_the_stories_being_built_finish_before_the_restart(self):
        io = Held([issue(1), issue(2), issue(3)], cap=2)
        claimed = []
        io.claim = lambda n, size="": claimed.append(n)
        io.code_head = lambda: f"head{int(len(claimed) >= 2)}"  # the head moves while both builders still run
        with mock.patch.object(cmd_drain, "wait", lambda *a, **k: io.gate.set() or wait(*a, **k)):
            _, spawned, _ = self.command(io, ["r", "--foreground"])
        self.assertEqual(([1, 2], [1, 2], 1), (sorted(io.started), sorted(io.closed), len(spawned)))

    def test_an_unmoved_head_restarts_nothing(self):
        _, spawned, rows = self.command(FakeIo([issue(1)]), ["r", "--foreground"])
        self.assertEqual(([], []), (spawned, rows))

    def test_a_gone_command_in_a_build_stops_new_stories_and_counts_nothing_against_the_story(self):
        io = FakeIo([issue(1), issue(2)], cap=1)
        io.build = mock.Mock(side_effect=cmd_drain.CommandGone(GONE_LINE))
        st = state()
        code, _ = quiet(cmd_drain.drain, io, st, sleep=lambda s: None)
        self.assertEqual((0, 1, [], 0), (code, io.build.call_count, st["blocked"], st["restarts"][1]))
        self.assertEqual(([1], [1]), (io.kept, io.released))
        self.notify.assert_called_once()
        self.assertIn("no longer exists", self.notify.call_args.args[0])
        self.assertEqual(1, len(io.comments))
        self.assertIn(GONE_LINE, io.comments[0][1])

    def test_a_gone_command_in_a_landing_starts_no_fix_round_and_notifies_once(self):
        io = FakeIo([issue(1, SHARED), issue(2), issue(3, SHARED)], cap=2)
        io.land = mock.Mock(side_effect=cmd_drain.CommandGone(GONE_LINE))
        st = state()
        quiet(cmd_drain.drain, io, st, sleep=lambda s: None)
        quiet(cmd_drain.drain, io, st, sleep=lambda s: None)  # the pass a queued story earns neither builds nor notifies again
        self.assertEqual(([1, 2], [], [1, 2]), (sorted(io.started), st["blocked"], sorted(io.kept)))
        self.assertEqual([1, 2], sorted(io.released))
        self.notify.assert_called_once()

    def real_io(self):
        repo = temp_dir(self)
        scratch_repo(repo, branch="main")
        return cmd_drain.Io(repo, "o/r"), repo

    def test_a_gone_command_in_the_builders_validation_ends_the_loop_after_one_session(self):
        io, repo = self.real_io()
        sessions = []
        reply = {"code": 0, "text": "done", "tokens": 1, "session_id": "s"}
        with mock.patch.object(cmd_drain.agent_loop.model, "run_cli", lambda *a, **k: sessions.append(k["model"]) or reply), \
                mock.patch.object(cmd_drain.agent_loop, "validation_command", return_value=["true"]), \
                mock.patch.object(cmd_drain.agent_loop, "validate", return_value=(False, f"gate\n{GONE_LINE}")):
            with self.assertRaisesRegex(cmd_drain.CommandGone, "'queue' is not a valid command"):
                quiet(io.build, issue(5), repo, "")
        self.assertEqual(1, len(sessions))

    def test_a_failed_landing_reads_the_gone_command_from_the_land_log(self):
        io, _ = self.real_io()
        log = self.home / "land-r-5.log"
        for text, gone in ((f"{GONE_LINE}\nRESULT validate-failed", True), ("FAIL: test_x\nRESULT validate-failed", False)):
            log.write_text(text)
            ran = subprocess.CompletedProcess([], 1, f"RESULT validate-failed (log: {log})\n", "")
            with mock.patch.object(cmd_drain.agent_loop, "log_stage"), mock.patch.object(cmd_drain.subprocess, "run", return_value=ran):
                if gone:
                    self.assertRaises(cmd_drain.CommandGone, io.land, Path("/wt/5"), 5)
                else:
                    self.assertFalse(io.land(Path("/wt/5"), 5)[0])

    def test_the_code_head_is_olivercodes_own_commit(self):
        io, repo = self.real_io()
        git(repo, "commit", "--allow-empty", "-qm", "base")
        with mock.patch.object(cmd_drain, "OC_ROOT", repo):
            self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), io.code_head())


BROKEN = "FAIL: tests/test_machine.py"


class NotTheStorysFailure(unittest.TestCase):
    """#1481: a failure the base shares costs the story nothing, and its backstop covers what earlier drains spent."""

    def setUp(self):
        self.home = temp_dir(self)
        mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}).start()
        self.notify = mock.patch.object(cmd_drain, "notify").start()
        self.addCleanup(mock.patch.stopall)
        for table in (cmd_drain.agent_loop.STORY_SIZE, cmd_drain.agent_loop.STORY_SLUG, cmd_drain.agent_loop.SPEND):
            mock.patch.dict(table).start()
        self.repo = temp_dir(self)
        scratch_repo(self.repo, branch="main")
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts" / "validate.sh").write_text("exit 1\n")
        self.io = cmd_drain.Io(self.repo, "o/r")

    def build(self, base):
        """Story 5's real build with each validation failing on BROKEN and the base check answering `base`. The output changes for three rounds and then repeats.
        Returns (outcome or error, models, base calls)."""
        models, calls, gates = [], [], iter("abcc")
        reply = {"code": 0, "text": "done", "tokens": 1, "session_id": ""}
        with mock.patch.object(cmd_drain.agent_loop.model, "run_cli", lambda *a, **k: models.append(k["model"]) or reply), \
                mock.patch.object(cmd_drain.agent_loop, "validate", lambda cwd: (False, f"gate {next(gates)}\n{BROKEN}\n")), \
                mock.patch.object(self.io, "base_failure", lambda fresh=False: calls.append(fresh) or base):
            try:
                out, _ = quiet(self.io.build, issue(5, "Size: S"), self.repo, "")
            except cmd_drain.BaseFails as exc:
                out = exc
        return out, models, calls

    def test_a_base_that_fails_the_same_way_stops_the_build_before_any_failure_counts(self):
        out, models, calls = self.build(BROKEN)
        self.assertIsInstance(out, cmd_drain.BaseFails)
        self.assertEqual((BROKEN, 1, [True]), (str(out), len(models), calls))  # one session, and the base was validated afresh

    def test_a_base_that_passes_or_fails_differently_counts_the_failure_and_steps_up(self):
        for base in ("", "FAIL: another gate"):
            out, models, calls = self.build(base)
            self.assertEqual((False, 4, 4), (out["done"], out["rounds"], len(calls)), base)
            self.assertNotEqual(models[0], models[-1], base)

    def test_the_story_is_held_with_the_reason_and_is_neither_restarted_nor_blocked(self):
        io = FakeIo([issue(1), issue(2)], cap=1)
        real = io.build
        def build(i, wt, note):
            if i["number"] == 1:
                io.started.append(1)
                raise cmd_drain.BaseFails(BROKEN)
            return real(i, wt, note)
        io.build = build
        st = state()
        quiet(cmd_drain.drain, io, st, sleep=lambda s: None)
        quiet(cmd_drain.drain, io, st, sleep=lambda s: None)  # a second pass of the same run does not take the held story again
        self.assertEqual(([1, 2], [2], [], [1], 0), (io.started, io.closed, st["blocked"], io.kept, st["restarts"][1]))
        self.assertEqual([1], [n for n, _ in io.comments])
        self.assertEqual([mock.call("#1 didn't land yet. It'll try again on its own.")], self.notify.call_args_list)
        self.assertEqual([False, True], io.fresh_checks[:2])  # the held story has the base validated again before the next pick
        self.assertIn("base branch fails validation with the same failing line", io.comments[0][1])
        self.assertIn(BROKEN, io.comments[0][1])

    def test_a_landing_that_fails_like_the_base_holds_the_story_with_no_fix_round(self):
        io = FakeIo([issue(1)], cap=1)
        io.land = mock.Mock(side_effect=cmd_drain.BaseFails(BROKEN))
        st = state()
        quiet(cmd_drain.drain, io, st, sleep=lambda s: None)
        self.assertEqual(([1], [], [1], [1]), (io.started, st["blocked"], io.kept, io.released))
        self.assertIn(BROKEN, io.comments[0][1])
        self.assertEqual([mock.call("#1 didn't land yet. It'll try again on its own.")], self.notify.call_args_list)

    def test_the_runs_last_message_counts_a_story_the_base_held_as_one_that_tries_again(self):
        io = FakeIo([issue(1)], cap=1)
        io.land = mock.Mock(side_effect=cmd_drain.BaseFails(BROKEN))
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=self.repo), mock.patch.object(cmd_drain, "slug_of", return_value="o/r"), \
                mock.patch.object(cmd_drain.cmd_dispatch, "is_engine", return_value=False):
            quiet(cmd_drain.command_drain, ["r", "--foreground"], io_factory=lambda *a, **k: io, sleep=lambda s: None)
        self.assertEqual(mock.call("Done: 0 stories landed. 1 will try again."), self.notify.call_args)

    def test_a_failed_landing_compares_the_validations_last_line_and_not_lands_own(self):
        log = self.home / "land-r-5.log"
        log.write_text(f"gate\n{BROKEN}\n--- validate failed, rerun\ngate\n{BROKEN}\n--- validate failed, rerun\nRESULT validate-failed\n")
        ran = subprocess.CompletedProcess([], 1, f"RESULT validate-failed (log: {log})\n", "")
        with mock.patch.object(cmd_drain.agent_loop, "log_stage"), mock.patch.object(cmd_drain.subprocess, "run", return_value=ran):
            with mock.patch.object(self.io, "base_failure", return_value=BROKEN), self.assertRaises(cmd_drain.BaseFails):
                self.io.land(Path("/wt/5"), 5)
            with mock.patch.object(self.io, "base_failure", return_value=""):
                self.assertFalse(self.io.land(Path("/wt/5"), 5)[0])

    def real(self, script):
        """A worktree whose validation is `script`, committed on main, with the repo as its own origin."""
        repo = temp_dir(self)
        scratch_repo(repo, branch="main")
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / "validate.sh").write_text(script)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "validation", "--no-verify")
        git(repo, "remote", "add", "origin", str(repo))
        return repo

    def gates(self, failed, nap=0, ran=10):
        """A validation on the real gate runner: a smoke gate naming `failed`, then a slower or faster gate that passes and prints after it."""
        summary = f"  Ran {ran} tests across 2 modules, 1 failed: {failed}"
        smoke = f"sleep {nap}; echo '{summary}'; echo '=== validate: python smoke tests FAILED ==='; exit 1"
        runner = REPO_ROOT / "scripts" / "lib" / "validate_gates.py"
        return f'exec "{sys.executable}" -B "{runner}" "smoke={smoke}" "limits=echo limits ok"\n'

    def verdicts(self, base, story):
        """Whether the build's check and a failed landing each blame the base, with both validations really run."""
        self.io = cmd_drain.Io(self.real(base), "o/r")
        wt, log = self.real(story), self.home / "land-r-5.log"
        with mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(worktrees=temp_dir(self))):
            passed, tail = cmd_drain.agent_loop.validate(wt)
            with open(log, "w", encoding="utf-8") as fh:
                self.assertEqual((False, False), (passed, cmd_drain.cmd_land._validates(wt, fh)))
                fh.write("RESULT validate-failed\n")
            found = []
            ran = subprocess.CompletedProcess([], 1, f"RESULT validate-failed (log: {log})\n", "")
            real_run = subprocess.run
            def run(command, *a, **k):
                return ran if "land" in command else real_run(command, *a, **k)
            with mock.patch.object(cmd_drain.agent_loop, "log_stage"), mock.patch.object(cmd_drain.subprocess, "run", run):
                for check in (lambda: self.io.blame(tail), lambda: self.io.land(wt, 5)):
                    try:
                        check()
                        found.append(False)
                    except cmd_drain.BaseFails:
                        found.append(True)
        return found

    def test_two_real_gate_runs_of_one_failure_match_whatever_their_timings_and_test_counts(self):
        self.assertEqual([True, True], self.verdicts(self.gates("test_machine"), self.gates("test_machine#2", nap=1.1, ran=12)))

    def test_two_real_gate_runs_that_fail_different_modules_do_not_match(self):
        self.assertEqual([False, False], self.verdicts(self.gates("test_machine"), self.gates("test_story")))

    def test_a_validation_that_writes_to_both_streams_matches_on_the_build_and_the_landing(self):
        script = "echo 'FAIL: tests/test_machine.py' >&2\necho gate done\nexit 1\n"
        self.assertEqual([True, True], self.verdicts(script, script + "# the story's copy\n"))

    def test_a_fresh_base_check_validates_a_tree_that_has_a_recorded_pass(self):
        with mock.patch.object(cmd_drain.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(cmd_drain, "placement_config", return_value=mock.Mock(worktrees=temp_dir(self))), \
                mock.patch.object(cmd_drain.cmd_land, "prepare_worktree"), \
                mock.patch.object(cmd_drain.validated, "is_validated", return_value=True), mock.patch.object(cmd_drain.validated, "working_tree", return_value="t"), \
                mock.patch.object(cmd_drain.agent_loop, "validation_command", return_value=["true"]), \
                mock.patch.object(cmd_drain.agent_loop, "validate_code", return_value=(1, f"gate\n{BROKEN}")):
            self.assertEqual(("", BROKEN), (self.io.base_failure(), self.io.base_failure(fresh=True)))

    def test_a_new_drain_starts_a_storys_backstop_from_what_the_run_log_says_it_spent(self):
        rows = [{"story": "story-5", "round": 1, "cost_usd": 11.50, "slug": "o/r"}, {"story": "story-5-review", "round": 1, "cost_usd": 0.20, "slug": "o/r"},
                {"story": "story-5", "round": 2, "cost_usd": 0.10},  # a row from before rows named their repo
                {"story": "story-5", "round": 3, "cost_usd": None, "slug": "o/r"}, {"story": "story-5-review", "round": 1, "cost_usd": 9.0, "slug": "o/r", "reader_failed": True},
                {"story": "story-5", "round": 1, "cost_usd": 9.0, "slug": "o/other"},
                {"story": "story-51", "round": 1, "cost_usd": 9.0, "slug": "o/r"}]
        (self.home / "run-log.jsonl.1").write_text(json.dumps(rows[0]) + "\n")
        (self.home / "run-log.jsonl").write_text("not json\n" + "".join(json.dumps(r) + "\n" for r in rows[1:]))
        self.io.claim(5, "S")
        self.assertAlmostEqual(11.80, cmd_drain.agent_loop.SPEND["story-5"])
        sessions = []
        reply = {"code": 0, "text": "done", "tokens": 1, "session_id": "", "cost_usd": 0.25}
        with mock.patch.object(cmd_drain.agent_loop.model, "run_cli", lambda *a, **k: sessions.append(1) or reply), \
                mock.patch.object(cmd_drain.agent_loop, "validate", return_value=(False, "own failure")), mock.patch.object(self.io, "base_failure", return_value=""):
            out, _ = quiet(self.io.build, issue(5, "Size: S", size="S"), self.repo, "")
        self.assertEqual((True, 1), (out["capped"], len(sessions)))  # $11.80 is under $12.00, and one round takes it past
        self.assertIn("$12.05", out["reason"])
        self.io.claim(5, "S")  # the next drain reads the row that round wrote
        self.assertAlmostEqual(12.05, cmd_drain.agent_loop.SPEND["story-5"])


class Remembering(FakeIo):
    newly_gated = cmd_drain.Io.newly_gated


class OwnerNotice(unittest.TestCase):
    """#1496: one needs-you notification per owner-gated story, across drain restarts."""

    def setUp(self):
        mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}).start()
        self.notify = mock.patch.object(cmd_drain, "notify").start()
        self.addCleanup(mock.patch.stopall)

    def run_over(self, *issues):
        """One new drain over `issues`, as a restart makes. Returns (its needs-you texts, its log)."""
        self.notify.reset_mock()
        _, out, _ = DrainCase.run_drain(self, Remembering(issues))
        return [c.args[0] for c in self.notify.call_args_list if "needs you" in c.args[0]], out

    def test_a_restarted_drain_logs_the_skip_and_sends_no_second_notification(self):
        gated = issue(1309, labels=["owner-action"])
        self.assertEqual(["#1309 needs you. The story says what to do."], self.run_over(gated)[0])
        told, out = self.run_over(gated)
        self.assertEqual(([], 1), (told, out.count("Skipped #1309: it is owner-gated")))

    def test_a_story_that_newly_waits_on_the_owner_is_named_once(self):
        self.assertEqual([], self.run_over(issue(1))[0])
        self.assertEqual(["#1 needs you. The story says what to do."], self.run_over(issue(1, labels=["owner-action"]))[0])

    def test_a_gate_that_is_cleared_and_returns_is_told_again(self):
        gated = issue(1, labels=["owner-action"])
        self.run_over(gated)
        self.assertEqual([], self.run_over(issue(1))[0])
        self.assertEqual(1, len(self.run_over(gated)[0]))

    def test_each_repo_remembers_its_own_stories(self):
        gated = [issue(1, labels=["owner-action"])]
        first, second = Remembering([]), Remembering([])
        second.slug = "o/other"
        self.assertEqual(([1], [1], [], []), tuple(io.newly_gated(gated) for io in (first, second, first, second)))


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
        self.assertEqual("-u", cmd[1])  # unbuffered, so a skip line is in the log before the run ends (#1510)
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
        self.assertRegex(lines[2], r"^Last run ended \d{4}-\d\d-\d\d \d\d:\d\d (EST|EDT): 2 stories landed, 1 stopped\.$")
        self.assertNotIn("reason", end)
        with mock.patch.object(cmd_drain, "drain", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        self.assertEqual("The run crashed.", self.rows()[-1]["reason"])
        for held, why in (({"base": {4: "FAIL: x"}}, "Stories wait because the base branch fails validation: FAIL: x."),
                          ({"red": "CI run u failed"}, "Routine stories wait because staging fails validation: CI run u failed.")):
            with mock.patch.object(cmd_drain, "drain", side_effect=lambda io, st, sleep=None: st.update(held) or 0):
                quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
            self.assertEqual(why, self.rows()[-1]["reason"])

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
        self.assertIn("Done: 2 stories landed. 1 will try again.", calls[0].args[0][2])

    def test_a_run_end_notification_counts_each_reason_a_story_was_not_started(self):  # #1456
        def work(io, st, sleep=None):
            st["skipped"].update({4: "blocker", 5: "owner", 6: "size", 7: "size", 8: "size"})
            st["closed"].append(8)  # a story that landed was started, so it is not counted
            return 0
        with mock.patch.object(cmd_drain, "drain", work), mock.patch.object(cmd_drain.subprocess, "run") as run:
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: FakeIo([]))
        calls = [c for c in run.call_args_list if c.args and c.args[0][0] == "osascript"]
        self.assertIn("Not started: 1 blocked by an open story, 1 owner-gated, 2 too large to build and not split.", calls[-1].args[0][2])

    def test_a_run_that_skips_every_story_says_why_in_watch_and_the_notification(self):  # #1510
        from lib import cmd_status
        io = FakeIo([issue(1, status="Backlog"), issue(2, status="Backlog"), issue(3)])
        io.deps = {3: [9]}
        with mock.patch.object(cmd_drain, "notify") as notify:
            quiet(cmd_drain.command_drain, ["r", "--foreground"], lambda repo, slug, parallel=None: io)
        self.assertEqual([], io.started)
        said = notify.call_args.args[0]
        self.assertIn("Not started: 1 blocked by an open story, 2 not ready to build. `olivercode watch r --until-exit` says why.", said)
        lines = []
        cmd_status.command_watch(["r", "--until-exit"], sleep=lambda s: None, out=lines.append, alive=lambda: False)
        streamed = cmd_status.watch_line(self.rows()[-1], self.rows())
        for line in (*lines, streamed):
            for skip in ("#1: its board Status is Backlog, not Ready.", "#2: its board Status is Backlog, not Ready.", "#3: it is blocked by open #9."):
                self.assertIn(f"Skipped {skip}", line)
        self.assertEqual(1, len(lines))

    def test_notify_sends_nothing_and_does_not_raise_without_osascript(self):
        with mock.patch.object(cmd_drain.subprocess, "run", side_effect=FileNotFoundError):
            cmd_drain.notify("anything")
        cmd_drain.notify("the suite's guard stands in for osascript")

    def test_watch_prints_each_new_stage_row_and_ends_with_the_run(self):
        from lib import cmd_status
        from lib.agent_loop import log_stage
        log_stage("story-168", "r", "building")  # already in the log before watch starts: the opening block shows it, the rows after it stream
        steps = iter([lambda: (log_stage("story-169", "r", "claimed"), log_stage("story-169", "r", "validating")),
                      lambda: (log_stage("story-169", "r", "landed"), log_stage("run-r", "r", "run-end", landed=1, stopped=0))])
        lines = []
        code = cmd_status.command_watch(["r"], sleep=lambda s: next(steps)(), out=lines.append, alive=lambda: True)
        self.assertEqual(0, code)
        self.assertEqual("The runner is running and no story is building.", lines[0])
        self.assertRegex(lines[2], r"^\d\d:\d\d (EST|EDT) #169 in r: claimed$")
        self.assertRegex(lines[3], r"^\d\d:\d\d (EST|EDT) #169 in r: validating$")
        self.assertRegex(lines[4], r"^\d\d:\d\d (EST|EDT) #169 in r: landed\. Building took under a minute, validation under a minute, landing under a minute, under a minute in all\.$")
        self.assertTrue(lines[5].endswith("1 story landed, 0 stopped."))

    def test_watch_keeps_reading_through_a_restart_and_ends_at_the_real_run_end(self):
        from lib import cmd_status
        from lib.agent_loop import log_stage
        steps = iter([lambda: (log_stage("run-r", "r", "restarting"), log_stage("run-r", "r", "run-end", landed=0, stopped=0)),
                      lambda: (log_stage("story-170", "r", "claimed"), log_stage("story-170", "r", "landed"), log_stage("run-r", "r", "run-end", landed=1, stopped=0))])
        lines = []
        code = cmd_status.command_watch(["r"], sleep=lambda s: next(steps)(), out=lines.append, alive=lambda: True)
        self.assertEqual(0, code)
        self.assertRegex(lines[2], r"^\d\d:\d\d (EST|EDT) #r in r: restarting$")  # the restarting row, then the old run's run-end line, both printed
        self.assertTrue(lines[3].startswith("Last run ended"))
        self.assertRegex(lines[4], r"^\d\d:\d\d (EST|EDT) #170 in r: claimed$")  # the restarted run's rows stream on
        self.assertRegex(lines[5], r"^\d\d:\d\d (EST|EDT) #170 in r: landed")
        self.assertTrue(lines[6].startswith("Last run ended") and lines[6].endswith("1 story landed, 0 stopped."))
        self.assertEqual(7, len(lines))

    def test_watch_exits_when_no_drain_holds_the_run_lock_and_leaves_the_drain_alone(self):
        from lib import cmd_status
        lines = []
        with mock.patch.object(cmd_status.run_lock, "active", return_value={}):
            code = cmd_status.command_watch(["r"], sleep=lambda s: None, out=lines.append)
        self.assertEqual(0, code)
        self.assertEqual(["No drain is running for r."], lines[-1:])
        self.assertTrue(lines[0].startswith("Runner idle: no story is building."))


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
        self.assertEqual([(1, f"Close refused: {io.refuse_close}")], io.stops_logged)  # #1291: the refusal is the stopped row's reason, #1297: only one row, #1371: bug intake reads the prefix
        self.assertEqual([], io.kept)  # keep_open would log a second stopped row

    def test_an_engine_story_on_staging_closes_like_any_landed_story(self):
        io = FakeIo([issue(1)])
        io.staged = lambda: True
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}, "tokens": 0})
        self.assertTrue(closed)
        self.assertEqual(([1], [], [1]), (io.closed, io.kept, io.released))

    def test_drain_start_closes_qa_stories_on_staging_and_names_the_rest(self):
        a, b, c = dict(issue(1), status="QA"), dict(issue(2), status="QA"), dict(issue(3), status="Backlog")
        io = FakeIo([a, b, c])
        io.staged = lambda: True
        io.on_main = {1}
        lines = []
        cmd_drain.close_waiting_in_qa(io, lines.append)
        self.assertEqual([1], io.closed)
        self.assertEqual(1, len(lines))
        self.assertIn("#2", lines[0])

    def test_a_qa_close_logs_stage_closed_and_a_landing_logs_landed(self):  # #1377
        a = dict(issue(1), status="QA")
        io = FakeIo([a])
        io.staged = lambda: True
        io.on_main = {1}
        stages = []
        io.close_by_script = lambda wt, n, why, stage="landed": stages.append(stage) or (True, "")
        cmd_drain.close_waiting_in_qa(io, lambda _: None)
        cmd_drain.finish(io, io.repo, 1, "pushed")
        self.assertEqual(["closed", "landed"], stages)

    def test_a_failed_board_read_puts_the_qa_close_off_and_the_next_read_closes_before_a_claim(self):  # #1345
        qa, new = dict(issue(1), status="QA"), issue(2)
        io = FakeIo([qa, new])
        io.staged = lambda: True
        io.on_main = {1}
        real, reads = io.list_open, []
        def flaky():
            reads.append(1)
            return None if len(reads) == 1 else real()
        io.list_open = flaky
        lines = []
        cmd_drain.close_waiting_in_qa(io, lines.append)
        self.assertEqual(([], 1), (io.closed, len(lines)))
        self.assertIn("Put off", lines[0])
        cmd_drain.drain(io, state(), sleep=lambda s: None, say=lambda t: None)
        self.assertEqual(1, io.closed[0])  # the QA story closes before the new story is built
        self.assertEqual([2], io.started)

    def test_the_drain_runs_the_qa_close_after_the_hold_wait(self):  # #1345
        io = FakeIo([dict(issue(1), status="QA")])
        io.staged = lambda: True
        io.on_main = {1}
        naps, offsets = [], [600, 0]
        blocked = lambda resource="": time.time() + offsets.pop(0) if len(offsets) > 1 else 0.0
        seen = []
        io.list_open = lambda: seen.append(naps[:]) or []
        with mock.patch.object(cmd_drain.gh_budget, "blocked_until", blocked), mock.patch.object(cmd_drain.agent_loop, "log_stage", lambda *a, **k: None):
            quiet(cmd_drain.drain, io, state(), sleep=naps.append)
        self.assertTrue(seen and seen[0])  # the first board read came after the sleep

    def test_drain_start_leaves_qa_stories_alone_in_a_repo_with_no_engine_branch(self):
        io = FakeIo([dict(issue(1), status="QA")])
        io.on_main = {1}
        cmd_drain.close_waiting_in_qa(io, lambda _: None)
        self.assertEqual([], io.closed)

    def test_a_landed_story_closes_by_script_without_a_second_session(self):
        io = FakeIo([issue(1)])
        closed, _ = cmd_drain.work_story(io, issue(1), {"sessions": 0, "restarts": {}, "tokens": 0})
        self.assertTrue(closed)
        self.assertEqual([1], io.closed)
        self.assertEqual(1, io.started.count(1))


if __name__ == "__main__":
    unittest.main()
