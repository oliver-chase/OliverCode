"""Launcher commands `version-cut` and `docs-check`: thin wrappers over the managed scripts in core/templates/project/scripts/.

OliverCode runs the same files it ships to fleet repos, so the cut and the docs check cannot drift from the managed copies.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from datetime import date
from pathlib import Path

from lib import cmd_land, denials, failure_log, launchd
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.version-cut"
USAGE = "Usage: olivercode version cut | version-cut --story REF [--day YYYY-MM-DD] [--commit] | version-cut --schedule --story REF | version-cut --unschedule"
TEMPLATE_SCRIPTS = OC_ROOT / "core" / "templates" / "project" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TEMPLATE_SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schedule(on: bool, story: str = "") -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["version-cut", "--commit", "--story", story], "version-cut.out", StartCalendarInterval={"Hour": 23, "Minute": 50}),
                            "version cut job", "`olivercode version-cut --commit --story STORY` runs daily at 23:50. Remove it with `olivercode version-cut --unschedule`.")


def command_version_cut(argv: list[str]) -> int:
    args = list(argv)
    opts = {"--day": date.today().isoformat(), "--story": ""}
    scheduling = [a for a in args if a in ("--schedule", "--unschedule")]
    while args:
        arg = args.pop(0)
        if arg in opts and args:
            opts[arg] = args.pop(0)
        elif arg not in ("--commit", *scheduling):
            return print(USAGE) or 1
    if len(scheduling) > 1 or (scheduling and scheduling[0] == "--unschedule" and opts["--story"]):
        return print(USAGE) or 1
    if scheduling == ["--unschedule"]:
        return schedule(False)
    if not opts["--story"]:
        return print("version-cut: pass --story REF, the story this cut is filed under.") or 1
    if scheduling:
        return schedule(True, opts["--story"])
    return cut_and_land(load("version_cut"), opts["--day"], opts["--story"])


def cut_and_land(cutter, day: str, story: str) -> int:
    """The cut holds the cut lock, so a land waits until it ends and a second cut refuses (#789)."""
    directory = cmd_land.log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / cmd_land.CUT_LOCK
    if cmd_land.cut_running(directory):
        return print("version-cut: a cut is already running.") or 1
    failure_log.write_private(lock, str(os.getpid()))  # renamed into place, so a reader never sees a half-written pid
    try:
        return _cut_and_land(cutter, day, story)
    finally:
        lock.unlink(missing_ok=True)


def _worktrees_dir():
    """Where the cut's worktree goes: under the owner's repoRoot when the local file names one, else beside this checkout (#1039)."""
    from lib import local_config
    root = local_config.load_local().get("repoRoot")
    return Path(root).expanduser() / "_worktrees" if root else OC_ROOT.parent / "_worktrees"


def _cut_and_land(cutter, day: str, story: str) -> int:
    """Commits the cut in a worktree of origin/main and lands it, so the installed checkout only fast-forwards (#785). `land` retries
    while main moves for up to ten minutes and ends sooner only on a rebase conflict or failed validation (#784, #789)."""
    subprocess.run(["git", "-C", str(OC_ROOT), "fetch", "-q", "origin"], capture_output=True)
    wt = _worktrees_dir() / f"oc-cut-{day}"
    if wt.exists():
        print(f"version-cut: {wt} already exists. Land it or remove it, then cut again")
        return 1
    added = subprocess.run(["git", "-C", str(OC_ROOT), "worktree", "add", "-b", f"version-cut-{day}", str(wt), "origin/main"], capture_output=True, text=True)
    if added.returncode:
        print(f"version-cut: could not add a worktree: {added.stderr.strip()}")
        return 1
    try:
        _, version = cutter.cut(wt, day, "origin/main")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"version-cut: no version cut: {exc}")
        _discard(wt, day)
        return 1
    if not version:
        _discard(wt, day)
        return 0
    cutter.commit_cut(wt, version, story)
    code = cmd_land.command_land([str(wt), story.lstrip("#")])
    if code:
        _queue_denial(wt, story.lstrip("#"))
    return code


def _discard(wt, day: str) -> None:
    """Remove the cut's worktree and branch when nothing was cut, even with half-written files, so the run leaves nothing behind (#1035)."""
    subprocess.run(["git", "-C", str(OC_ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)
    subprocess.run(["git", "-C", str(OC_ROOT), "branch", "-D", f"version-cut-{day}"], capture_output=True)


def _queue_denial(wt, story: str) -> None:
    """Queue a push the permission classifier denied, read from the land log (#787)."""
    log = cmd_land.log_dir() / f"land-{cmd_land._repo_name(wt)}-{story}.log"
    if log.is_file() and denials.record("git push origin HEAD:main", log.read_text(errors="replace"), "version-cut", str(wt)):
        print("version-cut: the push was denied. The exact command is in the owner queue (`olivercode owner list`).")


def command_docs_check() -> int:
    return load("docs_check").main([str(OC_ROOT)])
