"""One per-user launchd job: the bootout, plist and bootstrap steps every scheduled command shares."""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from lib import failure_log
from lib.cli import newer_python
from lib.local_config import OC_ROOT


def supported() -> bool:
    """launchd exists only on macOS."""
    return sys.platform == "darwin"


def agents_dir(home: Path | None = None) -> Path:
    """The folder holding a user's launchd plists."""
    return (home or Path.home()) / "Library" / "LaunchAgents"


def plist_path(label: str, home: Path | None = None) -> Path:
    return agents_dir(home) / f"{label}.plist"


def job_arguments(plist_file: Path) -> list:
    """The ProgramArguments of the job file PLIST_FILE, or [] when the file is missing, corrupt or has none."""
    try:
        args = plistlib.loads(plist_file.read_bytes()).get("ProgramArguments")
    except (OSError, ValueError, AttributeError):
        return []
    return args or []


def cron_line(plist: dict) -> str:
    """The crontab line that does what the plist's job does, from its interval or calendar timing."""
    if "StartInterval" in plist:
        minutes = max(1, plist["StartInterval"] // 60)
        when = f"*/{minutes} * * * *" if minutes < 60 else f"0 */{max(1, minutes // 60)} * * *"
    else:
        cal = plist.get("StartCalendarInterval", {})
        when = f"{cal.get('Minute', 0)} {cal.get('Hour', 0)} * * *"
    command = " ".join(shlex.quote(a) for a in plist["ProgramArguments"])
    log = shlex.quote(plist.get("StandardOutPath", "/dev/null"))
    return f"{when} {command} >> {log} 2>&1"


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
    domain, path = f"gui/{os.getuid()}", plist_path(label)
    if not supported():
        return _schedule_without_launchd(on, label, build, removed)
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


def _schedule_without_launchd(on: bool, label: str, build, removed: str) -> int:
    """Off macOS nothing is installed: print the crontab line to add, or the one to remove, and exit 1."""
    if not on:
        print(f"Scheduling uses launchd, which only macOS has, so nothing is installed here. Delete the {removed} line ({label}) from `crontab -e` if you added one.")
        return 1
    print(f"Scheduling uses launchd, which only macOS has, so the {removed} is not installed. Add this line with `crontab -e`:")
    print(cron_line(build()))
    return 1
