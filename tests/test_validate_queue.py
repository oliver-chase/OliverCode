"""Tests for the per-user validation queue: scripts/lib/validate_queue.py."""

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import validate_queue  # noqa: E402


class ValidateQueueTest(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_VALIDATE_SLOTS": "2"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_third_run_waits_while_two_live_runs_hold_the_slots(self):
        me = os.getpid()
        first, second = validate_queue.try_acquire(me), validate_queue.try_acquire(me)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        said = []
        self.assertIsNone(validate_queue.acquire(me, wait=1, poll=0.05, say=said.append))
        self.assertEqual(len(said), 2, "one line when the wait starts and one when the run goes ahead")
        self.assertIn("waiting for a validation slot", said[0])
        self.assertIn("2 of 2 held", validate_queue.show())
        validate_queue.release(first)
        self.assertIsNotNone(validate_queue.acquire(me, wait=1, poll=0.05, say=said.append))

    def test_a_dead_or_stale_holder_is_reaped(self):
        done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        dead = int(done.stdout)
        folder = validate_queue.slots_dir()
        folder.mkdir(parents=True)
        (folder / "slot-1.json").write_text(json.dumps({"pid": dead, "started": time.time()}))
        (folder / "slot-2.json").write_text(json.dumps({"pid": os.getpid(), "started": time.time() - validate_queue.HARD_CAP_SECONDS - 1}))
        self.assertEqual(validate_queue.reap(), ["slot-1.json", "slot-2.json"])
        self.assertIsNotNone(validate_queue.try_acquire(os.getpid()))

    def test_the_command_line_fails_open_and_validate_sh_takes_and_frees_a_slot(self):
        with mock.patch.object(validate_queue, "acquire", side_effect=OSError("disk full")):
            self.assertEqual(validate_queue.main(["acquire", "--pid", "1"]), 0)
        script = REPO_ROOT / "scripts" / "validate.sh"
        text = script.read_text(encoding="utf-8")
        snippet = (REPO_ROOT / "core" / "templates" / "project" / "scripts" / "validate-queue.snippet.sh").read_text(encoding="utf-8")
        self.assertIn(snippet, text, "validate.sh holds the one shared queue block")
        self.assertIn('VALIDATE_QUEUE_BIN="${SCRIPT_DIR}/lib/validate_queue.py"', text)
        template = (REPO_ROOT / "core" / "templates" / "project" / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn("acquire --pid $$", template)
        block = text[text.index("VALIDATE_QUEUE_BIN="):text.index("\nmain \"$@\"")]
        probe = temp_dir(self) / "probe.sh"
        probe.write_text(block + '\necho "$VALIDATE_QUEUE_SLOT"\n', encoding="utf-8")
        env = {**os.environ, "OLIVERCODE_VALIDATE_SLOT": "", "VALIDATE_QUEUE_SLOT": "", "SCRIPT_DIR": str(REPO_ROOT / "scripts"), "REPO_ROOT": str(REPO_ROOT)}
        out = subprocess.run(["bash", "-c", f'SCRIPT_DIR="$SCRIPT_DIR"; source "{probe}"'], capture_output=True, text=True, env=env)
        held = out.stdout.strip()
        self.assertRegex(held, r"slot-\d+\.json$", out.stdout + out.stderr)
        self.assertFalse(os.path.exists(held), "the EXIT trap frees the slot")


class QueueRobustnessTest(unittest.TestCase):
    """A fresh install, old or damaged state, a crashed holder and a reused pid all end with a working queue and a stderr line that names the repair (#757)."""

    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("OLIVERCODE_VALIDATE_SLOTS", "OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT", "OLIVERCODE_VALIDATE_HARD_CAP", "OLIVERCODE_VALIDATE_WAIT"):  # set by an old shell, they must change nothing
            os.environ.pop(name, None)
        validate_queue._TOLD.clear()

    def dead_pid(self):
        return int(subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True).stdout)

    def stderr_of(self, fn):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            result = fn()
        return result, err.getvalue()

    def test_the_wait_and_the_hard_cap_are_fixed_and_no_variable_changes_them(self):
        """#1072: nothing sets these, so they are constants."""
        self.assertFalse(hasattr(validate_queue, "wait_seconds") or hasattr(validate_queue, "hard_cap_seconds"))
        self.assertEqual(10 * 60, validate_queue.WAIT_SECONDS)
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_HARD_CAP": "1"}):
            folder = validate_queue.slots_dir()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "slot-1.json").write_text(json.dumps({"pid": os.getpid(), "started": time.time() - 60}))
            self.assertEqual([], validate_queue.reap())

    def test_a_fresh_install_with_no_state_folder_takes_and_frees_a_slot(self):
        self.assertFalse(self.home.exists() and any(self.home.iterdir()))
        slot = validate_queue.acquire(os.getpid(), "fresh", wait=1, poll=0.05, say=lambda m: None)
        self.assertIsNotNone(slot)
        self.assertTrue(slot.is_file())
        validate_queue.release(slot)
        self.assertFalse(slot.exists())

    def write_runs(self, loads):
        validate_queue.runs_log().parent.mkdir(parents=True, exist_ok=True)
        validate_queue.runs_log().write_text("".join(json.dumps({"at": 0, "wait": 0, "run": 1, "load": x}) + "\n" for x in loads))

    def test_the_slot_count_follows_cores_and_recent_load_unless_the_variable_sets_it(self):
        for name in ("OLIVERCODE_VALIDATE_SLOTS",):
            os.environ.pop(name, None)
        self.write_runs([3.0] * 10)
        for cores, expected in ((1, 1), (8, 1), (11, 1), (12, 2), (64, 2)):
            with mock.patch("os.cpu_count", return_value=cores):
                self.assertEqual(expected, validate_queue.slot_count(), cores)
        with mock.patch("os.cpu_count", return_value=None):
            self.assertEqual(1, validate_queue.slot_count())
        with mock.patch("os.cpu_count", return_value=16):
            self.write_runs([3.0] * 9)  # too few runs to know
            self.assertEqual(1, validate_queue.slot_count())
            self.write_runs([3.0] * 9 + [16.0])  # one run reached the core count
            self.assertEqual(1, validate_queue.slot_count())
            self.write_runs([40.0] + [3.0] * 10)  # only the last ten count
            self.assertEqual(2, validate_queue.slot_count())

    def test_the_variable_sets_the_slot_count_whatever_the_machine(self):
        self.write_runs([3.0] * 10)
        with mock.patch("os.cpu_count", return_value=64), mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "1"}):
            self.assertEqual(1, validate_queue.slot_count())

    def test_a_validation_logs_its_wait_run_time_and_load(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "1"}):
            for name in ("OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT"):
                os.environ.pop(name, None)
            self.assertEqual(0, validate_queue.run(["true"], poll=0.05))
        rows = validate_queue.recent_runs()
        self.assertEqual(1, len(rows))
        self.assertEqual({"at", "wait", "run", "load"}, set(rows[0]))

    def test_a_bad_slot_count_falls_back_to_the_machine_default_and_says_so(self):
        self.write_runs([3.0] * 10)
        with mock.patch("os.cpu_count", return_value=16), mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "lots"}):
            count, err = self.stderr_of(validate_queue.slot_count)
        self.assertEqual(2, count)
        self.assertIn("OLIVERCODE_VALIDATE_SLOTS='lots'", err)

    def test_a_crashed_holder_is_reclaimed_by_the_next_run_with_a_message(self):
        folder = validate_queue.slots_dir()
        folder.mkdir(parents=True)
        (folder / "slot-1.json").write_text(json.dumps({"pid": self.dead_pid(), "started": time.time()}))
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "1"}):
            slot, err = self.stderr_of(lambda: validate_queue.try_acquire(os.getpid()))
        self.assertEqual("slot-1.json", slot.name)
        self.assertIn("reclaimed validate slot slot-1.json", err)
        self.assertIn("is gone", err)

    def test_a_slot_whose_pid_was_reused_by_another_process_is_reclaimed(self):
        folder = validate_queue.slots_dir()
        folder.mkdir(parents=True)
        (folder / "slot-1.json").write_text(json.dumps({"pid": os.getpid(), "started": time.time(), "pid_started": "Thu Jan  1 00:00:00 1970"}))
        reaped, err = self.stderr_of(validate_queue.reap)
        self.assertEqual(["slot-1.json"], reaped)
        self.assertIn("now belongs to another process", err)

    def test_a_live_holder_keeps_its_slot_past_the_old_thirty_minute_limit(self):
        slot = validate_queue.try_acquire(os.getpid())
        later = time.time() + 31 * 60
        self.assertEqual([], validate_queue.reap(now=later))
        self.assertTrue(slot.exists())
        self.assertEqual(["slot-1.json"], validate_queue.reap(now=time.time() + validate_queue.HARD_CAP_SECONDS + 5))

    def test_old_corrupt_and_wrong_shaped_state_files_are_repaired_or_read(self):
        folder = validate_queue.slots_dir()
        folder.mkdir(parents=True)
        old = {"pid": os.getpid(), "started": time.time()}  # the shape before pid_started existed
        (folder / "slot-1.json").write_text(json.dumps(old))
        for name, text in (("slot-2.json", "{not json"), ("slot-3.json", "[1, 2]"), ("slot-4.json", json.dumps({"pid": "x", "started": 1}))):
            (folder / name).write_text(text)
            os.utime(folder / name, (time.time() - 3600, time.time() - 3600))
        reaped, err = self.stderr_of(validate_queue.reap)
        self.assertEqual(["slot-2.json", "slot-3.json", "slot-4.json"], reaped)
        self.assertTrue((folder / "slot-1.json").exists(), "an old-format slot with a live holder stays")
        self.assertIn("unreadable", err)
        self.assertIn("pid is not a number", err)
        self.assertIn(f"slot-1: pid {os.getpid()}", validate_queue.show())

    def test_a_state_file_where_the_slot_folder_belongs_is_moved_aside_and_named(self):
        self.home.mkdir(exist_ok=True)
        validate_queue.slots_dir().write_text("junk")
        slot, err = self.stderr_of(lambda: validate_queue.try_acquire(os.getpid()))
        self.assertIsNotNone(slot)
        self.assertIn("was a file, not a folder", err)
        self.assertTrue((self.home / "validate-slots.damaged").is_file())

    def test_a_waiter_that_runs_out_of_patience_goes_ahead_with_a_message_naming_why(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "1"}):
            held = validate_queue.try_acquire(os.getpid())
            said = []
            self.assertIsNone(validate_queue.acquire(os.getpid(), wait=0.2, poll=0.05, say=said.append))
        self.assertTrue(any("goes ahead without a slot" in m and "still held by a live run" in m for m in said), said)
        validate_queue.release(held)

    def test_a_command_already_inside_a_held_slot_takes_no_second_slot(self):
        with mock.patch.dict(os.environ, {"OLIVERCODE_VALIDATE_SLOTS": "1", "VALIDATE_QUEUE_SLOT": "/x/slot-1.json"}):
            held = validate_queue.try_acquire(os.getpid())
            self.assertEqual(0, validate_queue.run([sys.executable, "-c", "pass"], poll=0.05))
        validate_queue.release(held)

    def test_the_slot_variables_in_run_do_not_hide_a_slotless_value(self):
        with mock.patch.dict(os.environ, {"VALIDATE_QUEUE_SLOT": "none"}):
            self.assertFalse(validate_queue._inside_slot("validate"))

    def test_acquire_and_the_nested_run_check_agree_on_a_slotless_value(self):
        import io, contextlib
        for value, inside in (("none", False), ("/x/slot-1.json", True)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"VALIDATE_QUEUE_SLOT": value, "OLIVERCODE_VALIDATE_SLOT": ""}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), mock.patch.object(validate_queue, "acquire", return_value="/x/new.json"):
                    validate_queue.main(["acquire"])
                self.assertEqual(inside, validate_queue._inside_slot("validate"))
                self.assertEqual(inside, out.getvalue().strip() == "none")


if __name__ == "__main__":
    unittest.main()
