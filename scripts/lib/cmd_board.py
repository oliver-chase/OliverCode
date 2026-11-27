"""Launcher command `board`: every job that reads or repairs a fleet board, under one name (#676).

`olivercode board fit|sync` runs the module that owns the job: `fit` adds a Related line to a story body and names Files area paths
missing from main, and `sync` moves closed issues to Complete and adds open issues with no card. Each takes the flags its module documents.
"""

from __future__ import annotations

from lib import cmd_boardsweep, intake

USAGE = "Usage: olivercode board fit|sync [FLAGS]   (fit takes BODY_FILE --title TITLE --config FILE; sync takes --schedule and --unschedule)"


def command_board(argv: list[str]) -> int:
    run = {"fit": intake.command_fit, "sync": cmd_boardsweep.command_board_sweep}.get(argv[0] if argv else "")
    if run is None:
        print(USAGE)
        return 1
    return run(argv[1:])
