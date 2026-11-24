"""Launcher command `board`: every job that reads, repairs or files onto a fleet board, under one name (#676).

`olivercode board groom|sync|file` runs the module that owns the job: `groom` fixes and fills cards and runs the intake check, `sync`
moves closed issues to Complete and adds open issues with no card, and `file` creates a story only when its body passes the format
check (#1107). Each takes the flags its module documents.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from lib import cmd_boardsweep, cmd_groom

USAGE = ("Usage: olivercode board groom|sync|file [FLAGS]   (sync takes --schedule and --unschedule; "
         "file takes BODY_FILE --title TITLE --config FILE [--status STATUS])")


def command_file(argv: list[str]) -> int:
    """`olivercode board file BODY_FILE --title TITLE --config FILE [--status STATUS]` (#1107): a body with any part missing prints each
    part with its fix and files nothing. A complete body is created as an issue, and its Status, Priority, Size and Work type are set in
    one batch."""
    ap = argparse.ArgumentParser(prog="olivercode board file", description=command_file.__doc__.splitlines()[0])
    ap.add_argument("body_file", type=Path, help="the issue body, written from skills/backlog/references/story-template.md")
    ap.add_argument("--title", required=True)
    ap.add_argument("--config", required=True, type=Path, help="the repo's backlog config")
    ap.add_argument("--status", default="Backlog", help="Status for the new card (default Backlog)")
    args = ap.parse_args(argv)
    import batch_project
    import check_story_format
    try:
        body = args.body_file.read_text(encoding="utf-8")
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"{args.title}: not filed, the body or config cannot be read: {exc}")
        return 2
    problems = check_story_format.check_body(body, blocker=True, line_numbers=True, root=args.config.resolve().parent.parent)
    if problems:
        for part, fix in problems:
            print(f"MISSING {part}. Fix: {fix}")
        print(f"{args.title}: not filed; nothing was created on GitHub. Fix the parts above and file again.")
        return 1
    slug = f"{cfg['repoOwner']}/{cfg['repoName']}"
    number = (cmd_groom.gh(["api", "-X", "POST", f"repos/{slug}/issues", "-f", f"title={args.title}", "-F", f"body=@{args.body_file}",
                            "--jq", ".number"]) or "").strip()
    if not number.isdigit():
        print(f"{args.title}: not filed, GitHub refused to make the issue")
        return 1
    fields = {"status": args.status,
              "priority": check_story_format.PRIORITY.search(body + " ").group(1).upper(),
              "size": check_story_format.SIZE.search(body + " ").group(1).upper(),
              "workType": check_story_format.WORK_TYPE.search(body).group(1).capitalize()}
    with tempfile.TemporaryDirectory(prefix="olivercode-file-") as tmp:
        request = Path(tmp) / "fields.json"
        request.write_text(json.dumps({"issues": [{"number": int(number), "fields": fields}]}), encoding="utf-8")
        code = batch_project.main(["--config", str(args.config), "--input", str(request)])
    if code:
        print(f"{args.title}: filed as #{number}, but its board fields did not all set (exit {code}); rerun the batch for #{number}")
        return code
    print(f"{args.title}: filed as #{number}")
    return 0


def command_board(argv: list[str]) -> int:
    run = {"groom": cmd_groom.command_groom, "sync": cmd_boardsweep.command_board_sweep, "file": command_file}.get(argv[0] if argv else "")
    if run is None:
        print(USAGE)
        return 1
    return run(argv[1:])
