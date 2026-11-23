"""`olivercode drain REPO`: ordering, skips, overlap, restarts, blocker comment and the summary line. Every effect is injected."""

import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain  # noqa: E402


def issue(n, body="", labels=(), title=None):
    return {"number": n, "title": title or f"Story {n}", "body": body, "labels": [{"name": l} for l in labels], "comments": 0}


class FakeIo:
    def __init__(self, issues, cap=2, builds=None, land_ok=True, tokens=10):
        self.agent, self.moved, self.released, self.already, self.kept, self.on_main = "drain", [], [], False, [], set()
        self.ghost_land = False
        self.refuse_close = ""
        self.slug, self.issues, self.cap, self.builds, self.land_ok, self.tokens = "o/r", list(issues), cap, builds or {}, land_ok, tokens
        self.closed, self.comments, self.started, self.claims, self.lock = [], [], [], set(), threading.Lock()
        self.active, self.peak_overlap = set(), []

    def list_open(self):
        return [i for i in self.issues if i["number"] not in self.closed]

    def claimed(self, i): return i["number"] in self.claims
    def capacity(self): return self.cap
    def load_ok(self): return True
    def claim(self, n): pass
    def worktree(self, n): return Path(f"/wt/{n}")

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
        io = FakeIo([issue(1, "Edit `scripts/lib/cmd_drain.py`."), issue(2, "Edit `scripts/lib/cmd_drain.py`."), issue(3, "Edit `scripts/lib/cmd_land.py`.")], cap=3)
        self.run_drain(io)
        self.assertEqual(sorted(io.closed), [1, 2, 3])
        for active in io.peak_overlap:
            self.assertFalse({1, 2} <= active)

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

    def test_a_builder_that_already_landed_closes_the_story_without_landing_again(self):
        io = FakeIo([issue(1)])
        io.already = True
        io.land = lambda wt, n: self.fail("land ran for a story that was already on the default branch")
        self.run_drain(io)
        self.assertEqual((io.closed, io.moved), ([1], [1]))

    def test_a_landing_that_puts_nothing_on_the_default_branch_closes_nothing(self):
        io = FakeIo([issue(1)])
        io.ghost_land = True
        self.run_drain(io)
        self.assertEqual((io.closed, io.moved, io.kept), ([], [], [1]))

    def test_a_batched_story_without_its_own_commit_stays_open_and_returns_to_ready(self):
        io = FakeIo([])
        closed, _ = cmd_drain.work_story(io, {**issue(1), "mates": [issue(2)]}, state())
        self.assertEqual((closed, io.closed, io.kept, sorted(io.released)), (True, [1], [2], [1, 2]))

    def test_each_batched_story_closes_on_its_own_commit(self):
        io = FakeIo([])
        io.on_main.add(2)
        closed, _ = cmd_drain.work_story(io, {**issue(1), "mates": [issue(2)]}, state())
        self.assertEqual((closed, sorted(io.closed), io.kept), (True, [1, 2], []))

    def test_a_batch_that_landed_nothing_closes_no_story(self):
        io = FakeIo([])
        io.ghost_land = True
        cmd_drain.work_story(io, {**issue(1), "mates": [issue(2)]}, state())
        self.assertEqual((io.closed, sorted(io.kept)), ([], [1, 2]))

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

    def test_the_brief_carries_the_batched_stories_and_the_resume_note(self):
        lead = {**issue(7, "Do it.\nSize: XS"), "mates": [{"number": 8, "title": "Mate", "body": "Do eight."}]}
        self.io.resumed[7] = "Earlier partial work is present on branch story/7."
        with mock.patch.object(cmd_drain.agent_loop, "run_loop", return_value={"done": True}) as run_loop:
            self.io.build(lead, Path("/wt/7"), "")
        brief = run_loop.call_args.args[0]
        self.assertIn("builds 2 small stories that share files: #7, #8", brief)
        self.assertIn("Earlier partial work is present on branch story/7.", brief)

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


if __name__ == "__main__":
    unittest.main()


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
