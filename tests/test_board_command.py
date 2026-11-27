"""`olivercode board` and the `manager` message subcommands send each job to the module that owns it (#676)."""

import sys
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_board  # noqa: E402


class TestBoardCommand(unittest.TestCase):
    def test_each_board_job_gets_its_own_flags(self):
        for job, module, fn in (("fit", "intake", "command_fit"), ("sync", "cmd_boardsweep", "command_board_sweep")):
            with mock.patch.object(getattr(cmd_board, module), fn, return_value=7) as run:
                self.assertEqual(cmd_board.command_board([job, "--schedule"]), 7)
            run.assert_called_once_with(["--schedule"])

    def test_an_unknown_job_prints_the_usage(self):
        for argv in ([], ["sweep"], ["groom"]):
            with mock.patch("builtins.print") as out:
                self.assertEqual(cmd_board.command_board(argv), 1)
            out.assert_called_once_with(cmd_board.USAGE)


