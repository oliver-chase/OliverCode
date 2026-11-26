"""Claims and shared state files keep both writes when two processes write at once, and no agent deletes a remote branch unasked (#1033)."""

import json
import os
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
from lib import cmd_dispatch, cmd_owner, failure_log, gh_budget, local_config  # noqa: E402
import log_action  # noqa: E402


def together(*jobs):
    """Run each job in its own thread and wait for all of them."""
    threads = [threading.Thread(target=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


class SharedState(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_GH_POINTS_FLOOR": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_two_owner_steps_added_at_once_get_two_ids(self):
        together(*[lambda i=i: cmd_owner.add("s", f"step {i}", command="c", error="e") for i in range(8)])
        ids = [i["id"] for i in cmd_owner.items()]
        self.assertEqual(sorted(ids), list(range(1, 9)))

    def test_two_local_claims_both_stay(self):
        together(*[lambda i=i: cmd_dispatch._local_claim("o/r", i, 1000.0, write=f"agent-{i}") for i in range(8)])
        claims = json.loads((self.home / "dispatch-claims.json").read_text())
        self.assertEqual(8, len(claims))

    def test_a_bad_budget_value_does_not_fail_the_import(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_GH_WRITES_PER_HOUR": "lots"}):
            self.assertEqual(7, gh_budget._env_int("OLIVERCODE_GH_WRITES_PER_HOUR", 7))

    def test_two_noted_limits_keep_the_longer_hold(self):
        together(lambda: gh_budget.note_limit(seconds=100, resources=("rest",), fetch=lambda: {}),
                 lambda: gh_budget.note_limit(seconds=900, resources=("graphql",), fetch=lambda: {}))
        self.assertTrue(gh_budget.blocked_until("rest") and gh_budget.blocked_until("graphql"))


class QueueAndTimings(SharedState):
    def test_a_replay_and_an_enqueue_together_keep_both_rows(self):
        gh_budget.enqueue(["gh", "issue", "close", "1"], cwd=str(self.home))

        sent = []

        def run(argv, cwd):  # a command queued while the replay runs
            sent.append(argv[-1])
            if argv[-1] == "1":
                gh_budget.enqueue(["gh", "issue", "close", "2"], cwd=cwd)
            return subprocess.CompletedProcess(argv, 0, "", "")
        together(lambda: gh_budget.replay(run), lambda: gh_budget.enqueue(["gh", "issue", "close", "3"], cwd=str(self.home)))
        left = [r["argv"][-1] for r in gh_budget._read()]
        self.assertEqual(["1", "2", "3"], sorted(set(sent) | set(left)))  # each row was sent or is still queued
        self.assertIn("2", left)

    def test_saved_timings_drop_modules_that_no_longer_exist(self):
        from lib import smoke_runner
        smoke_runner.save_timings({"old": 1.0, "kept": 2.0})
        smoke_runner.save_timings({"kept": 3.0})
        self.assertEqual({"kept": 3.0}, smoke_runner.load_timings())

    def test_a_live_run_renews_its_claim_and_a_released_one_stops(self):
        from lib import cmd_drain
        posted = []
        io = cmd_drain.Io(self.home, "o/r", "agent-x", runner=lambda a: subprocess.CompletedProcess(a, 0, "", ""))
        with mock.patch.object(cmd_dispatch.log_action, "post_comment", lambda *a: posted.append(a)), mock.patch.object(gh_budget, "refusal", return_value=""), \
                mock.patch.object(gh_budget, "reserve_write", return_value=""):
            io.claimed_at[5] = 1000.0
            io.refresh_claims(now=1000.0 + 60)
            self.assertEqual([], posted)
            io.refresh_claims(now=1000.0 + 3600)
            self.assertEqual(1, len(posted))
            self.assertEqual(1000.0 + 3600, io.claimed_at[5])
        self.assertIn("agent-x", cmd_dispatch._local_claim("o/r", 5, 1000.0 + 3700))


class ClaimRace(unittest.TestCase):
    def test_only_the_earliest_claim_builds(self):
        comments = []
        lock = threading.Lock()

        def runner(args):
            with lock:
                if "-f" in args:
                    comments.append(args[2].removeprefix("body="))
                    return subprocess.CompletedProcess([], 0, "https://example.invalid/c\n", "")
                return subprocess.CompletedProcess([], 0, "".join(json.dumps({"body": b}) + "\n" for b in comments), "")

        codes = {}

        def claim(name):
            def go():
                codes[name] = log_action.main(["--repo", "o/r", "--story", "9", "--agent", name, "--role", "claim"], runner=runner,
                                              out=mock.MagicMock(), err=mock.MagicMock())
            return go
        together(claim("a"), claim("b"))
        self.assertEqual([0, 1], sorted(codes.values()))

    def test_a_dead_claim_is_replaced_and_a_refresh_stands(self):
        old = log_action.build_claim("a", datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc))
        new = log_action.build_claim("b", datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc))
        refresh = log_action.build_claim("a", datetime(2026, 11, 17, 11, 30, tzinfo=timezone.utc))
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

        def status(*bodies):
            text = "".join(json.dumps({"body": b}) + "\n" for b in bodies)
            return log_action.claim_status("o/r", 9, lambda _a: subprocess.CompletedProcess([], 0, text, ""), now)
        self.assertEqual("claimed by b at 2026-11-17T11:00:00Z", status(old, new))
        self.assertTrue(status(new, refresh).startswith("claimed by b"))
        self.assertEqual("claimed by a at 2026-11-17T11:30:00Z", status(old, refresh))


class RemoteBranches(unittest.TestCase):
    def test_remote_deletion_needs_the_owners_setting(self):
        from lib import placement
        cfg = temp_dir(self) / "local.json"
        cfg.write_text("{}")
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(cfg)}):
            self.assertFalse(local_config.delete_merged_remote_branches())
            cfg.write_text('{"deleteMergedRemoteBranches": true}')
            self.assertTrue(local_config.delete_merged_remote_branches())
        with mock.patch.object(placement, "remote_branches", return_value=["x"]) as remote, mock.patch.object(placement, "worktrees", return_value=[]):
            self.assertEqual([], placement.clean(apply=True, remote=False))
            remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
