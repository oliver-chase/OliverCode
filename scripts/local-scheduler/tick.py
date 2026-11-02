#!/usr/bin/env python3
"""OliverCode local scheduler -- tick.

One launchd agent fires this every 15 minutes, plus once on load (which
also covers "the Mac just woke up"). This script decides what is due by
elapsed time against marker files, so a tick missed while the Mac sleeps is
caught up by the next tick, where plain cron would skip the job silently.

The plist's ProgramArguments invoke the python3 binary directly. A bash
script spawned by launchd from under ~/Documents has no Full Disk Access
and fails "Operation not permitted" on its first cd.

A job's marker stays untouched on failure, so the job stays "due" and the
next tick (15 minutes later) retries without waiting a full interval.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OC_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(OC_ROOT / "scripts"))
from lib.scheduler_constants import AUDIT_FLEET_INTERVAL_S, PUSH_FLEET_INTERVAL_S  # noqa: E402
STATE_DIR = Path.home() / "Library" / "Application Support" / "olivercode-scheduler"
LOG_DIR = STATE_DIR / "logs"

JOB_TIMEOUT_S = 30 * 60

JOBS = [
    ("push-fleet", STATE_DIR / "last-push-fleet", PUSH_FLEET_INTERVAL_S, ["push-fleet"]),
    ("audit-fleet", STATE_DIR / "last-audit-fleet", AUDIT_FLEET_INTERVAL_S, ["audit-fleet"]),
]


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def seconds_since(marker: Path) -> float:
    if not marker.exists():
        return float("inf")
    return time.time() - marker.stat().st_mtime


def touch(marker: Path) -> None:
    marker.touch()


def log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (LOG_DIR / "scheduler.log").open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")


def run_job(name: str, marker: Path, argv: list[str]) -> None:
    log(f"{name}: starting")
    job_log = LOG_DIR / f"{name}.log"
    try:
        result = subprocess.run(
            [sys.executable, str(OC_ROOT / "scripts" / "olivercode"), *argv],
            cwd=str(OC_ROOT), capture_output=True, text=True,
            timeout=JOB_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        log(f"{name}: TIMED OUT after {JOB_TIMEOUT_S // 60} minutes, will retry next tick")
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with job_log.open("a", encoding="utf-8") as f:
        f.write(f"\n=== {stamp} ===\n{result.stdout}\n{result.stderr}\n")
    if result.returncode == 0:
        touch(marker)
        log(f"{name}: OK")
    else:
        # Marker deliberately left untouched -- stays due, next tick retries.
        log(f"{name}: FAILED (exit {result.returncode}) -- see {job_log}, will retry next tick")


def main() -> int:
    ensure_dirs()
    for name, marker, interval_s, argv in JOBS:
        if seconds_since(marker) >= interval_s:
            run_job(name, marker, argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
