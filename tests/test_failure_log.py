"""The failure log: a blocked commit adds one line holding the date, repo, gate and reason, and the log stays outside git."""

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

sys.path.insert(0, str(REPO_ROOT / "scripts"))


class TestHookWrites(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hook-writes-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.dir)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_a_file_written_through_record_is_mode_600(self):
        from lib import failure_log
        log = self.dir / "failures.log"
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            failure_log.record("gate", "reason", "repo")
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_two_writers_at_once_leave_the_file_intact(self):
        from lib import failure_log
        path = self.dir / "fires" / "guard.json"
        stop, bad = threading.Event(), []

        def read():
            while not stop.is_set():
                try:
                    json.loads(path.read_text())
                except FileNotFoundError:
                    pass
                except ValueError:
                    bad.append(path.read_text())

        def write(n):
            for i in range(150):
                path.parent.mkdir(parents=True, exist_ok=True)
                failure_log.write_atomic(path, json.dumps({"ran": f"{n}-{i}" * 200}) + "\n")

        reader = threading.Thread(target=read)
        reader.start()
        writers = [threading.Thread(target=write, args=(n,)) for n in range(2)]
        [t.start() for t in writers]
        [t.join() for t in writers]
        stop.set()
        reader.join()
        self.assertEqual([], bad)
        self.assertEqual([], [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"])

    def test_the_home_is_walked_for_modes_once_and_not_on_every_call(self):
        from lib import failure_log
        failure_log.home()
        with mock.patch.object(failure_log, "privatize") as walk:
            failure_log.home()
        walk.assert_not_called()


class TestFailureLog(GateHarness):
    def setUp(self):
        super().setUp()
        self.log = self.tmp.parent / (self.tmp.name + "-failures.log")
        self.addCleanup(lambda: self.log.unlink(missing_ok=True))

    def test_a_blocked_commit_writes_one_line_with_the_gate_and_reason(self):
        self.stage("config.py", 'KEY = "sk-' + "a" * 32 + '"\n')
        self.assertBlocked("gate 1", OLIVERCODE_FAILURE_LOG=str(self.log))
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        when, repo, gate, reason = lines[0].split("\t")
        self.assertRegex(when, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(repo, self.tmp.name)
        self.assertEqual(gate, "Secrets")
        self.assertIn("BLOCKED", reason)

    def test_a_machine_without_olivercode_gets_no_log(self):
        home = self.log.parent / (self.tmp.name + "-stranger")
        home.mkdir()
        self.addCleanup(home.rmdir)
        self.stage("a.py", 'K = "sk-' + "e" * 32 + '"\n')
        self.assertBlocked("gate 1", HOME=str(home), OLIVERCODE_FAILURE_LOG="", OLIVERCODE_HOME="")
        self.assertFalse((home / ".olivercode").exists())

    def test_a_passing_commit_writes_nothing(self):
        self.stage("notes.txt", "Plain notes.\n")
        self.assertAllowed(OLIVERCODE_FAILURE_LOG=str(self.log))
        self.assertFalse(self.log.exists())

    def test_the_log_is_not_inside_the_repo_so_git_never_sees_it(self):
        self.stage("config.py", 'KEY = "sk-' + "b" * 32 + '"\n')
        self.assertBlocked("gate 1", OLIVERCODE_FAILURE_LOG=str(self.log))
        self.assertNotRegex(git(self.tmp, "status", "--short").stdout, re.compile(r"failures"))
