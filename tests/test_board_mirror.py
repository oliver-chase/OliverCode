"""Tests for the shared local board copy: scripts/lib/board_mirror.py."""

import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import board_mirror  # noqa: E402


class TestImportsAsALibModule(unittest.TestCase):
    def test_board_mirror_imports_as_lib_and_bare(self):
        # As lib.board_mirror: every other lib module is imported that way, so the flat sibling import of gh_budget fails here alone.
        # Bare, from scripts/lib: batch_project.py and check_board_hygiene.py import it that way.
        rows = [
            ("as lib.board_mirror", REPO_ROOT / "scripts", "import lib.board_mirror"),
            ("bare from scripts/lib", REPO_ROOT / "scripts" / "lib", "import board_mirror"),
        ]
        for name, cwd, statement in rows:
            with self.subTest(name):
                result = subprocess.run([sys.executable, "-c", statement], cwd=cwd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


class TestBoardMirror(unittest.TestCase):
    def setUp(self):
        home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_fresh_copy_is_read_without_fetching(self):
        fetch = mock.Mock(return_value=[{"id": 1}])
        board_mirror.read("o", 1, fetch)
        self.assertEqual([{"id": 1}], board_mirror.read("o", 1, fetch))
        self.assertEqual(1, fetch.call_count)

    def test_a_stale_copy_is_fetched_again(self):
        fetch = mock.Mock(return_value=[])
        board_mirror.read("o", 1, fetch)
        board_mirror.read("o", 1, fetch, clock=lambda: 10 ** 11)
        self.assertEqual(2, fetch.call_count)

    def test_no_cache_always_fetches(self):
        fetch = mock.Mock(return_value=[])
        board_mirror.read("o", 1, fetch, use_cache=False)
        board_mirror.read("o", 1, fetch, use_cache=False)
        self.assertEqual(2, fetch.call_count)

    def test_a_write_makes_the_next_read_fetch(self):
        fetch = mock.Mock(return_value=[])
        board_mirror.read("o", 1, fetch)
        board_mirror.invalidate()
        board_mirror.read("o", 1, fetch)
        self.assertEqual(2, fetch.call_count)

    def test_agents_reading_together_cause_one_fetch(self):
        calls = []

        def slow_fetch():
            calls.append(1)
            threading.Event().wait(0.2)
            return [{"id": 1}]

        results = []
        threads = [threading.Thread(target=lambda: results.append(board_mirror.read("o", 1, slow_fetch))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(1, len(calls))
        self.assertEqual([[{"id": 1}]] * 4, results)

    def test_a_reader_never_sees_a_half_written_copy(self):
        board = [{"id": i, "title": "x" * 50} for i in range(20000)]
        path = board_mirror._path("o", 1)
        board_mirror.read("o", 1, lambda: board)
        errors = []

        def reader():
            for _ in range(60):
                try:
                    board_mirror.read("o", 1, lambda: board)
                except ValueError as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for _ in range(10):
            os.utime(path, (1, 1))  # stale, so one reader refreshes while the others read
            board_mirror.read("o", 1, lambda: board, use_cache=False)
        for t in threads:
            t.join()
        self.assertEqual([], errors)
