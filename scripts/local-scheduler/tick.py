#!/usr/bin/env python3
"""OliverCode local scheduler -- tick.

Mirrors the fleet's proven pattern (a product repo's own scripts/local-scheduler/
tick.mjs): one launchd agent fires this every 15 minutes, plus once on load (which
also covers "the Mac just woke up"). This script decides what is actually due by
elapsed time against marker files, not exact-minute alignment -- a missed tick
while the Mac sleeps just means the next tick catches up, instead of the job
silently skipping the way plain cron does.

Python, not bash, invoked directly (not via a shebang'd bash wrapper): a bare
bash spawned by launchd from under ~/Documents has no Full Disk Access of its
own on this machine and fails "Operation not permitted" just cd-ing in -- a real,
previously-hit failure mode (TCC-1) in the sibling scheduler this one mirrors.
Invoking the python3 binary directly in the plist's ProgramArguments sidesteps it
the same way that one invokes node directly instead of a bash entry point.

Deliberately does NOT touch a job's marker on failure -- the job stays "due" so
the next tick (15 minutes later) retries, instead of waiting a full interval.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OC_ROOT = SCRIPT_DIR.parent.parent
STATE_DIR = Path.home() / "Library" / "Application Support" / "olivercode-scheduler"
LOG_DIR = STATE_DIR / "logs"

# Early-fire margins, same discipline as the sibling scheduler this mirrors: a
# little short of the true interval so a tick never drifts to just-barely-late.
PUSH_FLEET_INTERVAL_S = 3 * 60 * 60 - 10 * 60   # ~3h, matching cadence confirmed with OliverCBot
AUDIT_FLEET_INTERVAL_S = (6 * 24 + 20) * 60 * 60  # ~6.83 days, matching the sibling scheduler's weekly margin

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
    result = subprocess.run(
        [sys.executable, str(OC_ROOT / "scripts" / "olivercode"), *argv],
        cwd=str(OC_ROOT), capture_output=True, text=True,
        timeout=30 * 60,
    )
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
