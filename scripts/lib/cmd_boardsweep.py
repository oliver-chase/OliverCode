"""Launcher command `board sync`: keeps every board in step with its issues through the API (#798).

GitHub offers no API to switch on a board's built-in "Item closed" and "Auto-add to project" workflows, so this sweep does
their work. For each board with a backlog config (the boards the backlog skill reads) it reads the board once and the
repo's issues through REST, which spends no GraphQL points, then queues two kinds of change through `batch_project.py`:
a card whose issue is closed moves to Status Complete, and an open issue with no card is added with Status Backlog.
`batch_project.py` queues the writes while GraphQL is on hold and applies them in aliased mutations after the reset.
`--schedule` installs a launchd job that runs the sweep every thirty minutes, and `--unschedule` removes it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from lib import cmd_sweep, gh_budget, launchd
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.board-sweep"
USAGE = "Usage: olivercode board sync [--dry-run] | [--schedule | --unschedule]"
SCRIPTS = OC_ROOT / "skills" / "backlog" / "scripts"
FINISHED = ("complete", "done")
OPENING = "Backlog"


def plan(items: list[dict], issues: list[dict], config: dict) -> tuple[list[int], list[int]]:
    """(numbers of closed issues whose card is not finished, numbers of open issues with no card) for the config's own repo."""
    sys.path.insert(0, str(SCRIPTS))
    import check_board_hygiene  # noqa: PLC0415
    options = config.get("fields", {}).get("status", {}).get("options", {})
    finished = next((k for k in options if k.lower() in FINISHED), None)
    found = check_board_hygiene.status_drift(items, {x["number"]: x["state"] for x in issues}, f"{config['repoOwner']}/{config['repoName']}", finished)
    return [n for n, k in found if k == "close" and finished], [n for n, k in found if k == "add" and OPENING in options]


def request(config: dict, close: list[int], add: list[int]) -> dict:
    """The batch_project.py input for one board's changes."""
    options = config["fields"]["status"]["options"]
    finished = next(k for k in options if k.lower() in FINISHED)
    return {"issues": [{"number": n, "fields": {"status": finished}} for n in close]
            + [{"number": n, "fields": {"status": OPENING}} for n in add]}


def read(config_path: Path) -> tuple[dict, list[dict], list[dict]]:
    """(config, board items, repo issues) through REST and the shared local board copy. Exits when the board cannot be read."""
    sys.path.insert(0, str(SCRIPTS))
    import board_rest  # noqa: PLC0415
    import check_board_hygiene as hygiene  # noqa: PLC0415
    config = json.loads(config_path.read_text(encoding="utf-8"))
    items = hygiene.load_items(config, use_cache=False)
    issues = board_rest.repo_issues(f"{config['repoOwner']}/{config['repoName']}", hygiene.run_gh_soft)
    if issues is None:
        raise RuntimeError("the repo's issues could not be read through REST")
    return config, items, issues


def apply(config_path: Path, payload: dict) -> int:
    """Hand PAYLOAD to batch_project.py, which queues it while GraphQL is held."""
    sys.path.insert(0, str(SCRIPTS))
    import batch_project  # noqa: PLC0415
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
    try:
        return batch_project.main(["--config", str(config_path), "--input", fh.name])
    finally:
        Path(fh.name).unlink(missing_ok=True)


def run(board_list=cmd_sweep.boards, reader=read, applier=apply, dry_run: bool = False, out=print) -> int:
    """Sweep every board. Returns 1 when a board could not be read or a write failed."""
    failed = 0
    for name, path in board_list():
        try:
            config, items, issues = reader(path)
        except (RuntimeError, OSError, ValueError, KeyError, SystemExit) as exc:
            out(f"{name}: the sweep did not run ({str(exc).splitlines()[0][:120] if str(exc) else 'the board could not be read'})")
            failed = 1
            continue
        close, add = plan(items, issues, config)
        if not close and not add:
            out(f"{name}: in step")
            continue
        text = f"{name}: {len(close)} closed card(s) to Complete, {len(add)} open issue(s) to add"
        if dry_run:
            out(text + " (dry run, nothing written)")
            continue
        held = gh_budget.refusal()
        code = applier(path, request(config, close, add))
        out(text + (f", queued until the GraphQL reset ({held.split('. ')[0]})" if held and not code else "") + ("" if not code else ", a write failed and stays queued"))
        failed = failed or int(bool(code))
    return failed


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["board", "sync"], "board-sweep.out", StartInterval=1800), "board sweep job",
                            "`olivercode board sync` runs every thirty minutes. Remove it with `olivercode board sync --unschedule`.")


def command_board_sweep(argv: list[str]) -> int:
    if argv in (["--schedule"], ["--unschedule"]):
        return schedule(argv == ["--schedule"])
    if argv not in ([], ["--dry-run"]):
        print(USAGE)
        return 1
    code = run(dry_run=bool(argv))
    if not argv:
        from lib import city  # local import: city reads the modules that import this one
        from lib.local_config import OC_ROOT
        try:
            city.refresh(OC_ROOT)  # the page stays current when no drain runs; launchd starts in /, so the root is explicit (#1350)
        except Exception:  # shortcut: any failure is swallowed, since the page is a view and the next sync retries it
            pass
    return code
