"""Launcher command `board`: every job that reads or repairs a fleet board, under one name (#676).

`olivercode board groom|sync` runs the module that owns the job: `groom` fixes and fills cards and runs the intake check, and `sync`
moves closed issues to Complete and adds open issues with no card. Each takes the flags its module documents.
"""

from __future__ import annotations

from lib import cmd_boardsweep, cmd_groom

USAGE = "Usage: olivercode board groom|sync [FLAGS]   (sync takes --schedule and --unschedule)"


def command_board(argv: list[str]) -> int:
    run = {"groom": cmd_groom.command_groom, "sync": cmd_boardsweep.command_board_sweep}.get(argv[0] if argv else "")
    if run is None:
        print(USAGE)
        return 1
    return run(argv[1:])
