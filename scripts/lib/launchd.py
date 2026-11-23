"""One per-user launchd job: the bootout, plist and bootstrap steps every scheduled command shares."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from lib import failure_log
from lib.cli import newer_python
from lib.local_config import OC_ROOT


def job_path() -> str:
    """The PATH every job runs with: the folder holding gh first, then the usual install folders and the launchd default."""
    found = shutil.which("gh")
    folders = ([str(Path(found).parent)] if found else []) + ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    return os.pathsep.join(dict.fromkeys(folders))


def job(label: str, args: list[str], log: str, **timing) -> dict:
    """The plist of a job that runs `olivercode ARGS` and writes its output to LOG in the failure-log folder."""
    out = str(failure_log.home() / log)
    return {"Label": label, "ProgramArguments": [newer_python() or sys.executable, str(OC_ROOT / "scripts" / "olivercode"), *args],
            "StandardOutPath": out, "StandardErrorPath": out, **timing}


def schedule(on: bool, label: str, build, removed: str, installed: str) -> int:
    """Replace the job LABEL with the plist BUILD returns, or remove it when ON is false."""
    domain, path = f"gui/{os.getuid()}", Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    if not on:
        path.unlink(missing_ok=True)
        print(f"Removed the {removed} ({label}).")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    failure_log.home().mkdir(parents=True, exist_ok=True)
    plist = build()
    plist.setdefault("EnvironmentVariables", {}).setdefault("PATH", job_path())
    path.write_bytes(plistlib.dumps(plist))
    ran = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if ran.returncode:
        print(f"Wrote {path} but launchctl refused it: {ran.stderr.strip()}")
        return 1
    print(f"Installed {label}: {installed}")
    return 0


def command_with_schedule(argv: list[str], usage: str, schedule_job, run) -> int:
    """The shared body of a command that runs once or installs and removes its daily job."""
    if argv in (["--schedule"], ["--unschedule"]):
        return schedule_job(argv == ["--schedule"])
    if argv:
        print(usage)
        return 1
    return run()
