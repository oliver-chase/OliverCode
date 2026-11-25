"""#992: one run per repo, whichever thread starts it. The lock, the joined queue, the takeover, the session line and the status line."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain, cmd_status, run_lock  # noqa: E402

session = load_script("scripts/hooks/session_check.py")
NOW = 1_700_000_000.0


class FakeIo:
    def __init__(self, slug="o/r"):
        self.slug, self.released, self.drained, self.readied = slug, [], 0, []

    def release(self, n): self.released.append(n)
    def ready(self, n): self.readied.append(n)


class LockCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patcher.start()
        os.environ.pop("OLIVERCODE_HEADLESS", None)  # restored with the patch when the test ends
        self.addCleanup(patcher.stop)
        self.alive = {111: True, 222: True}

    def acquire(self, who, pid, now=NOW, want=None):
        return run_lock.acquire("o/r", who, now, page="/h/status.md", want=want, pid=pid, alive=lambda p: self.alive.get(p, False))


class TestRunLock(LockCase):
    def test_a_second_run_starts_no_builder_and_its_stories_join_the_queue(self):
        self.assertEqual(({}, {}, ""), self.acquire("drain r", 111))
        run_lock.beat("o/r", 111, NOW + 5, [42])
        held, taken, _ = self.acquire("dispatch 77", 222, NOW + 10, want=[77])
        self.assertEqual((111, [77], {}), (held["pid"], held["queue"], taken))
        text = run_lock.describe(held, NOW + 10)
        for part in ("drain r", "process 111", "building #42", "/h/status.md"):
            self.assertIn(part, text)
        self.assertEqual([77], run_lock.take_queue("o/r", 111))
        self.assertEqual([], run_lock.take_queue("o/r", 111))

    def test_a_dead_process_or_a_silent_run_does_not_block(self):
        self.acquire("drain r", 111)
        self.alive[111] = False
        held, taken, why = self.acquire("drain r", 222, NOW + 1)
        self.assertEqual(({}, 111, "its process 111 is gone"), (held, taken["pid"], why))
        self.alive[222] = True
        held, taken, why = self.acquire("drain r", 111, NOW + 1 + (run_lock.STALL_MINUTES + 1) * 60)
        self.assertEqual(({}, 222), (held, taken["pid"]))
        self.assertIn("has not reported for 31 minutes", why)

    def test_a_beat_keeps_the_lock_live_and_a_displaced_holder_cannot_rewrite_it(self):
        self.acquire("drain r", 111)
        run_lock.beat("o/r", 111, NOW + 25 * 60)
        self.assertEqual(111, self.acquire("dispatch 1", 222, NOW + 40 * 60, want=[1])[0]["pid"])
        self.alive[111] = False
        self.acquire("drain r", 222, NOW + 41 * 60)
        run_lock.beat("o/r", 111, NOW + 42 * 60, [9])
        self.assertEqual(222, run_lock.active("o/r", NOW + 42 * 60, lambda p: True)["pid"])

    def test_release_keeps_the_lock_while_a_queued_story_remains(self):
        self.acquire("drain r", 111)
        self.acquire("dispatch 5", 222, NOW + 1, want=[5])
        self.assertEqual([5], run_lock.release("o/r", 111))
        self.assertEqual([], run_lock.release("o/r", 111))
        self.assertEqual({}, run_lock.active("o/r", NOW + 2, lambda p: True))

    def test_different_repos_hold_separate_locks(self):
        self.acquire("drain r", 111)
        self.assertEqual(({}, {}, ""), run_lock.acquire("o/other", "drain other", NOW, pid=222, alive=lambda p: True))


class TestBuildingElsewhere(LockCase):
    def test_it_counts_the_live_builders_of_other_repos_only(self):
        """#1055: the machine-wide limit counts what other runs are building, never this repo's own run or a dead one."""
        alive = lambda p: self.alive.get(p, False)
        run_lock.acquire("o/r", "drain r", NOW, pid=111, alive=alive)
        run_lock.beat("o/r", 111, NOW, [1, 2])
        run_lock.acquire("o/s", "drain s", NOW, pid=222, alive=alive)
        run_lock.beat("o/s", 222, NOW, [3, 4, 5])
        run_lock.acquire("o/t", "drain t", NOW, pid=333, alive=alive)
        run_lock.beat("o/t", 333, NOW, [6])
        self.assertEqual(3, run_lock.building_elsewhere("o/r", NOW, alive))
        self.assertEqual(2, run_lock.building_elsewhere("o/s", NOW, alive))
        self.assertEqual(5, run_lock.building_elsewhere("o/u", NOW, alive))


class TestTakeRun(LockCase):
    def take(self, io, who, want=None, pid=None):
        with mock.patch.object(run_lock.os, "getpid", return_value=pid), mock.patch.object(cmd_drain, "status_page", return_value="/h/status.md"), \
                mock.patch.object(run_lock, "pid_alive", lambda p: self.alive.get(p, False)), mock.patch.object(cmd_drain.time, "time", return_value=NOW):
            return quiet(cmd_drain.take_run, io, "o/r", who, want)

    def test_the_second_start_names_the_holder_and_the_page(self):
        self.assertEqual(True, self.take(FakeIo(), "drain r", pid=111)[0])
        started, out = self.take(FakeIo(), "dispatch 77", [77], pid=222)
        self.assertEqual(False, started)
        for part in ("No second run starts", "drain r", "process 111", "/h/status.md", "Story #77 joins its queue"):
            self.assertIn(part, out)

    def test_a_takeover_says_so_and_releases_the_dead_runs_claims(self):
        self.take(FakeIo(), "drain r", pid=111)
        run_lock.beat("o/r", 111, NOW, [42])
        self.alive[111] = False
        io = FakeIo()
        started, out = self.take(io, "drain r", pid=222)
        self.assertEqual((True, [42]), (started, io.released))
        self.assertEqual([42], io.readied)  # #1201: the dead run's card returns to Ready
        self.assertIn("Took over the run lock", out)
        self.assertIn("resumes from the board", out)

    def test_a_dead_runs_claim_is_free_at_once_and_a_live_runs_is_not(self):
        """#1201: live_claim reads the run lock, so a killed run's claim is free before the two hours pass."""
        from lib import cmd_dispatch
        self.take(FakeIo(), "drain r", pid=111)
        run_lock.beat("o/r", 111, NOW, [42])
        cmd_dispatch._local_claim("o/r", 42, NOW, write="drain")
        cmd_dispatch._local_claim("o/r", 43, NOW, write="drain")
        with mock.patch.object(run_lock, "pid_alive", lambda p: True):
            self.assertIn("held by drain", cmd_dispatch.live_claim(None, "o/r", 42, {}, NOW))
        with mock.patch.object(run_lock, "pid_alive", lambda p: False):
            self.assertEqual("", cmd_dispatch.live_claim(None, "o/r", 42, {}, NOW))
            self.assertIn("held by drain", cmd_dispatch.live_claim(None, "o/r", 43, {}, NOW))  # not a story the dead run was building: the two-hour rule decides

    def test_a_drain_that_finds_a_live_run_builds_nothing(self):
        built = []
        factory = lambda repo, slug, parallel=None: built.append(slug) or FakeIo(slug)
        run_lock.acquire("o/r", "drain r", __import__("time").time(), pid=os.getpid())
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/x")), mock.patch.object(cmd_drain, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(cmd_drain, "drain", side_effect=AssertionError("a second run started")), mock.patch.object(run_lock.os, "getpid", return_value=os.getpid() + 1):
            code, out = quiet(cmd_drain.command_drain, ["r"], factory)
        self.assertEqual(0, code)
        self.assertIn("No second run starts", out)
        self.assertIn("every open story joins its queue in priority order", out)


class TestNotices(LockCase):
    def test_a_session_in_a_repo_with_an_active_run_is_told_the_story_in_flight(self):
        repo = temp_dir(self)
        self.acquire("drain r", 111)
        run_lock.beat("o/r", 111, __import__("time").time(), [42])
        with mock.patch.object(session.repo_gates, "repo_root", return_value=repo), mock.patch("lib.repo_state.origin", return_value="o/r"), \
                mock.patch.object(run_lock, "pid_alive", return_value=True):
            lines = session.run_notes(repo)
        self.assertEqual(1, len(lines))
        self.assertIn("building #42", lines[0])
        self.assertIn("filed as a story and joins the queue", lines[0])

    def test_no_line_without_a_run_and_none_in_a_headless_builder(self):
        repo = temp_dir(self)
        with mock.patch.object(session.repo_gates, "repo_root", return_value=repo), mock.patch("lib.repo_state.origin", return_value="o/r"):
            self.assertEqual([], session.run_notes(repo))
        self.acquire("drain r", 111)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HEADLESS": "1"}):
            self.assertEqual([], session.run_notes(repo))

    def test_status_names_the_run(self):
        run_lock.acquire("o/r", "drain r", 0.0, pid=os.getpid())
        lines = []
        with mock.patch.object(run_lock, "dead_reason", return_value=""):
            cmd_status.run("o/r", count=lambda s, st: 1, fetch=lambda s, since: [], out=lines.append)
        self.assertTrue(any(l.strip().startswith("Run ") and "drain r" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
