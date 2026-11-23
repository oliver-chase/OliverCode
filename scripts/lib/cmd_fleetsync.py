"""Launcher command `fleet-sync`: keep every fleet repo level with origin with no model call (#626).

`olivercode fleet-sync` walks the fleet repos cloned on this machine. A repo on its default branch with a clean tree is
fetched, pulled with rebase, validated by its own `scripts/validate.sh` (or `npm run validate`) when it holds unpushed
commits, and pushed. It never resolves a conflict (a failed rebase is aborted), never touches uncommitted files, never
forces a push and never switches branch. Each repo it cannot bring level goes into the owner queue (`olivercode owner`)
with the command it ran and the error, once per repo, and prints on the last lines. Template drift stays with
`olivercode sync-hooks --commit`. `--schedule` installs a launchd job that runs it at 03:30 and `--unschedule` removes it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lib import cmd_owner, launchd
from lib.local_config import OC_ROOT
from lib.repo_profiles import iter_fleet, load_repo_profiles

LABEL = "com.olivercode.fleet-sync"
USAGE = "Usage: olivercode fleet-sync [--schedule | --unschedule]"
TIMEOUT = 900


def _run(path: Path, *cmd: str) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{cmd[0]}: {exc}"
    return done.returncode, (done.stdout + done.stderr).strip()


def validate(path: Path) -> tuple[int, str]:
    """The repo's own validation: scripts/validate.sh, else an npm validate script. Neither means nothing to run."""
    if (path / "scripts" / "validate.sh").is_file():
        return _run(path, "bash", "scripts/validate.sh")
    if (path / "package.json").is_file() and '"validate"' in (path / "package.json").read_text(encoding="utf-8", errors="ignore"):
        return _run(path, "npm", "run", "validate")
    return 0, ""


def sync_repo(path: Path, check=validate) -> tuple[str, str, str]:
    """(result line, command tried, error). The command and error are empty when the repo is level."""
    code, branch = _run(path, "git", "symbolic-ref", "--short", "-q", "HEAD")
    code2, upstream = _run(path, "git", "rev-parse", "--abbrev-ref", "@{upstream}")
    if code or code2:
        return "no upstream on a branch", "git rev-parse --abbrev-ref @{upstream}", upstream or "HEAD is detached or has no upstream"
    if upstream.split("/")[-1] != branch or branch not in ("main", "master"):
        return f"on {branch}, left alone", "git symbolic-ref --short HEAD", f"on branch {branch}, not the default branch"
    _, dirty = _run(path, "git", "status", "--porcelain", "--untracked-files=no")
    if dirty:
        return f"{len(dirty.splitlines())} uncommitted file(s)", "git status --porcelain", "uncommitted changes need a commit or a discard"
    for cmd in (("git", "fetch", "--quiet"), ("git", "pull", "--rebase", "--quiet")):
        code, text = _run(path, *cmd)
        if code:
            _run(path, "git", "rebase", "--abort")
            return "could not pull", " ".join(cmd), text[-400:]
    _, ahead = _run(path, "git", "rev-list", "--count", "@{upstream}..HEAD")
    if ahead in ("", "0"):
        return "level with origin", "", ""
    code, text = check(path)
    if code:
        return "validation failed", "validate", text[-400:]
    code, text = _run(path, "git", "push", "--quiet")
    if code:
        return "push refused", "git push", text[-400:]
    return f"pushed {ahead} commit(s)", "", ""


def run(repos=None, check=validate, out=print) -> int:
    if repos is None:
        profiles, _ = load_repo_profiles(OC_ROOT)
        repos = [(name, path) for name, _, path in iter_fleet(profiles, OC_ROOT.parent) if (path / ".git").exists()]
    failed = []
    queued = {i["step"] for i in cmd_owner.items() if i["status"] == "open"}
    for name, path in repos:
        line, command, error = sync_repo(path, check)
        out(f"{name}: {line}")
        if command:
            failed.append(name)
            step = f"Bring {name} level with origin: {line}"
            if step not in queued:
                cmd_owner.add("fleet-sync", step, command, error)
    out(f"{len(failed)} of {len(repos)} repo(s) need the owner" + (": " + ", ".join(failed) if failed else "."))
    return 0


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["fleet-sync"], "fleet-sync.out", StartCalendarInterval={"Hour": 3, "Minute": 30}), "fleet sync job",
                            "`olivercode fleet-sync` runs at 03:30. Remove it with `olivercode fleet-sync --unschedule`.")


def command_fleet_sync(argv: list[str]) -> int:
    return launchd.command_with_schedule(argv, USAGE, schedule, run)
