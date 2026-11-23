"""Launcher command `board`: every job that reads or repairs a fleet board, under one name (#676).

`olivercode board groom|sweep|sync|burndown` runs the module that owns the job: `groom` fills and fixes cards, `sweep` reports
drift to the owner queue, `sync` moves closed issues to Complete and adds open issues with no card, and `burndown` counts open
issues per repo. Each takes the flags its module documents, `--schedule` and `--unschedule` among them.
"""

from __future__ import annotations

from lib import cmd_boardsweep, cmd_burndown, cmd_groom, cmd_sweep

USAGE = "Usage: olivercode board groom|sweep|sync|burndown [FLAGS]   (--schedule installs the job, --unschedule removes it)"


def command_board(argv: list[str]) -> int:
    run = {"groom": cmd_groom.command_groom, "sweep": cmd_sweep.command_sweep,
           "sync": cmd_boardsweep.command_board_sweep, "burndown": cmd_burndown.command_burndown}.get(argv[0] if argv else "")
    if run is None:
        print(USAGE)
        return 1
    return run(argv[1:])
