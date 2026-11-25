"""#1096: a commit the commit-msg gate keeps blocking returns the story to Backlog, and each restart is told why."""

import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
from lib import cmd_drain  # noqa: E402
from test_drain import FakeIo, issue, state  # noqa: E402


class BlockingIo(FakeIo):
    blocks: dict = {}
    backlogged: list = []

    def commit_block(self, n, wt): return self.blocks.get(n)
    def backlog(self, n): self.backlogged = self.backlogged + [n]


class CommitBlockCase(unittest.TestCase):
    def test_the_same_commit_msg_block_on_every_round_returns_the_story_to_backlog(self):
        block = {"gate": "commit-msg", "reason": "[commit-msg] BLOCKED: the commit message names no story."}
        io = BlockingIo([issue(1)], builds={1: [{"done": False, "reason": "commit refused"} for _ in range(4)]})
        io.blocks, io.backlogged = {1: block}, []
        notes = []
        build = io.build
        io.build = lambda i, wt, note: (notes.append(note), build(i, wt, note))[1]
        st = state()
        cmd_drain.drain(io, st, sleep=lambda s: None, say=lambda t: None)
        self.assertEqual(io.started, [1, 1, 1, 1])
        self.assertEqual(io.backlogged, [1])
        self.assertEqual(io.released, [1])
        self.assertEqual(st["blocked"], [1])
        self.assertIn("commit-msg gate", io.comments[-1][1])
        self.assertIn("names no story", io.comments[-1][1])
        self.assertEqual(notes[0], "")
        self.assertIn("[commit-msg] BLOCKED: the commit message names no story.", notes[1])
        self.assertIn("Rewrite the commit message", notes[1])

    def test_commit_block_in_reads_the_newest_commit_msg_block_of_the_run(self):
        log = temp_dir(self) / "failures.log"
        log.write_text("2026-11-23T16:00:00Z\tR-1\thook\t[commit-msg] BLOCKED: old\n2026-11-23T16:20:00Z\tR-1\thook\t[commit-msg] BLOCKED: the commit message names no story.\n2026-11-23T16:21:00Z\tR-1\tSecrets\tBLOCKED: key\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"OLIVERCODE_FAILURE_LOG": str(log)}):
            self.assertEqual(cmd_drain.commit_block_in("R-1", "2026-11-23T16:10:00Z"), {"gate": "commit-msg", "reason": "[commit-msg] BLOCKED: the commit message names no story."})
            self.assertIsNone(cmd_drain.commit_block_in("R-1", "2026-11-23T16:30:00Z"))


if __name__ == "__main__":
    unittest.main()


class FullMachineCase(unittest.TestCase):
    def test_a_drain_waits_at_most_twenty_minutes_then_stops_naming_the_holder(self):
        class Full(FakeIo):
            def holders(self): return ["o/other"]
        io = Full([issue(1)])
        io.cap = 0
        sleeps, lines = [], []
        cmd_drain.drain(io, state(), sleep=sleeps.append, say=lines.append)
        self.assertEqual(20 * 60, sum(sleeps))
        self.assertEqual([], io.started)
        self.assertTrue(any("o/other" in line and "20 minutes" in line for line in lines))
