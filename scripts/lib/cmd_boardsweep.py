"""Launcher command `board sync`: keeps every board in step with its issues through the API (#798).

GitHub offers no API to switch on a board's built-in "Item closed" and "Auto-add to project" workflows, so this sweep does
their work. For each board with a backlog config (the boards `olivercode board sweep` reads) it reads the board once and the
repo's issues through REST, which spends no GraphQL points, then queues two kinds of change through `batch_project.py`:
a card whose issue is closed moves to Status Complete, and an open issue with no card is added with Status Backlog.
`batch_project.py` queues the writes while GraphQL is on hold and applies them in aliased mutations after the reset.
`--schedule` installs a launchd job that runs the sweep every thirty minutes, and `--unschedule` removes it.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from lib import board_mirror, cmd_sweep, gh_budget, launchd
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.board-sweep"
USAGE = "Usage: olivercode board sync [--dry-run] | [--schedule | --unschedule]"
SCRIPTS = OC_ROOT / "skills" / "backlog" / "scripts"
FINISHED = ("complete", "done")
OPENING = "Backlog"
KEPT = "board-sweep-issues.json"  # each board's repo issues from its last full read, with the fingerprint of the open issues they came from (#1020)


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


def fingerprint(opened: list[dict]) -> str:
    """A fingerprint of the open issues: each number with its last update. A new, closed or edited issue changes it."""
    return hashlib.sha256(json.dumps(sorted((i.get("number"), i.get("updated_at", "")) for i in opened)).encode()).hexdigest()


def open_read(repo: str, run) -> list[dict] | None:
    """The open issues of REPO, pull requests left out, through REST, which a GraphQL hold does not block. None when the read fails. The read is
    issue_count's, so the sweep and the status count share one definition of an open issue (#1020)."""
    import issue_count  # noqa: PLC0415

    def rest(args: list[str]) -> SimpleNamespace:  # the sweep's runner returns stdout or None; the issue read wants a process result
        out = run(["api", *args])
        return SimpleNamespace(returncode=0 if out is not None else 1, stdout=out or "")

    return issue_count.issue_rows(repo, runner=rest)


def _kept_all() -> dict:
    try:
        return json.loads((gh_budget.home() / KEPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read(config_path: Path) -> tuple[dict, list[dict], list[dict]]:
    """(config, board items, repo issues). The open issues are read on every sweep, and their fingerprint decides whether the repo's full issue list and
    the board are read again: they are read only when it changed, so an unchanged repo costs one open read (#1020). Raises when the board or the issues
    cannot be read."""
    sys.path.insert(0, str(SCRIPTS))
    import board_rest  # noqa: PLC0415
    import check_board_hygiene as hygiene  # noqa: PLC0415
    config = json.loads(config_path.read_text(encoding="utf-8"))
    repo = f"{config['repoOwner']}/{config['repoName']}"
    opened = open_read(repo, hygiene.run_gh_soft)
    if opened is None:
        raise RuntimeError("the repo's open issues could not be read through REST")
    stamp = fingerprint(opened)
    kept = _kept_all().get(str(config_path)) or {}
    if kept.get("stamp") == stamp:
        return config, hygiene.load_items(config), kept.get("issues") or []
    issues = board_rest.repo_issues(repo, hygiene.run_gh_soft)
    if issues is None:
        raise RuntimeError("the repo's issues could not be read through REST")
    everything = _kept_all()
    everything[str(config_path)] = {"stamp": stamp, "issues": issues}
    try:
        (gh_budget.home() / KEPT).write_text(json.dumps(everything), encoding="utf-8")
    except OSError:
        pass  # without the copy the next sweep rereads the issues, which is the cost this avoids and no failure
    return config, hygiene.load_items(config, use_cache=False), issues


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
        board_mirror.invalidate()  # the sweep queued or applied a change, so the next sweep reads the board live rather than from the copy (#1020)


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
    return run(dry_run=bool(argv))
