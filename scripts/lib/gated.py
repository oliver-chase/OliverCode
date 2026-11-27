"""Launcher command `gated`: run a scheduled job's command only when a check finds work, with no model call for the check (#998).

`olivercode gated [--job NAME] CHECK -- COMMAND...` runs CHECK first. CHECK is one shell string, such as `./has_work.sh`. Exit 0 means there
is work, so COMMAND starts and its exit code is returned. Exit 1 means there is none, so COMMAND never starts and the run is logged as skipped.
Any other exit code is a broken check: COMMAND does not start, the run is logged as failed and the code is returned, so launchd shows it.
Every run adds one line to gated-runs.jsonl in the OliverCode home, which `olivercode status` reads for the runs a gate skipped.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import subprocess
import time
from pathlib import Path

from lib import failure_log

USAGE = "Usage: olivercode gated [--job NAME] CHECK -- COMMAND..."
MODEL_COMMAND = re.compile(r"(^|[/<>\s])claude(\s|<|$)")
WEEK = 7 * 86400


def log_path() -> Path:
    return failure_log.home() / "gated-runs.jsonl"


def record(job: str, result: str, starts_model: bool, now: float | None = None) -> None:
    """One line for a gated run: its job, `ran`, `skipped` or `failed`, and whether the command starts a model."""
    row = {"at": time.time() if now is None else now, "job": job, "result": result, "model": starts_model}
    failure_log.append_private(log_path(), json.dumps(row) + "\n")


def run_gated(job: str, check: str, command: list[str], runner=subprocess.run) -> int:
    """Run CHECK, then COMMAND only when CHECK exits 0. Returns 0 for a skip, COMMAND's code for a run and CHECK's code for a broken check."""
    starts_model = bool(MODEL_COMMAND.search(" " + shlex.join(command)))
    checked = runner(check, shell=True).returncode
    if checked == 1:
        record(job, "skipped", starts_model)
        print(f"gated {job}: no work, skipped with no model call")
        return 0
    if checked != 0:
        record(job, "failed", starts_model)
        print(f"gated {job}: the check exited {checked}, so the command did not start. A check exits 0 with work and 1 with none")
        return checked
    record(job, "ran", starts_model)
    return runner(command).returncode


def command_gated(argv: list[str]) -> int:
    job = ""
    if argv[:1] == ["--job"] and len(argv) > 1:
        job, argv = argv[1], argv[2:]
    if "--" not in argv:
        print(USAGE)
        return 1
    split = argv.index("--")
    check, command = " ".join(argv[:split]), argv[split + 1:]
    if not check.strip() or not command:
        print(USAGE)
        return 1
    try:
        name = job or os.environ.get("OLIVERCODE_JOB") or Path(shlex.split(check)[0]).name
    except ValueError:  # an unbalanced quote in CHECK
        print(USAGE)
        return 1
    return run_gated(name, check, command)


def wrapper_line(text: str, is_task: bool, name: str) -> str:
    """The exact `olivercode gated` line to put in place of an ungated job's command. A launchd job's own command goes after `--`,
    and a scheduled task's goes after `--` as a headless run of the task by name."""
    if is_task:
        return f'olivercode gated --job {shlex.quote(name)} CHECK -- claude -p "Run the scheduled task {name}"'
    command = ""
    try:
        args = [str(a) for a in plistlib.loads(text.encode("utf-8")).get("ProgramArguments", [])]
        command = args[2] if len(args) == 3 and args[1] == "-c" else shlex.join(args)
    except (ValueError, plistlib.InvalidFileException):
        pass
    return f"olivercode gated --job {shlex.quote(name)} CHECK -- {command or 'COMMAND'}"


def skipped_week(path: Path | None = None, now: float | None = None) -> dict[str, tuple[int, int, int]]:
    """Per job over the last seven days: (runs, runs skipped, model sessions avoided). A skipped run avoids a session when its command starts a model."""
    since = (time.time() if now is None else now) - WEEK
    out: dict[str, list[int]] = {}
    try:
        lines = (path or log_path()).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            row = json.loads(line)
            if float(row["at"]) < since:
                continue
            counts = out.setdefault(str(row["job"]), [0, 0, 0])
        except (ValueError, KeyError, TypeError):
            continue
        counts[0] += 1
        if row.get("result") == "skipped":
            counts[1] += 1
            counts[2] += bool(row.get("model"))
    return {job: (c[0], c[1], c[2]) for job, c in sorted(out.items())}


def savings_lines(path: Path | None = None, now: float | None = None) -> list[str]:
    """One line per gated job for `olivercode status`: its runs skipped and the model sessions they avoided over the last seven days."""
    return [f"Gate {job}: {skipped} of {runs} runs skipped in the last 7 days, {avoided} model session{'s' if avoided != 1 else ''} avoided."
            for job, (runs, skipped, avoided) in skipped_week(path, now).items()]
