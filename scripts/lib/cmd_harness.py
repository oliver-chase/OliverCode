"""Launcher command `job`: run an agent job under the gates."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import date
from pathlib import Path

from lib import failure_log
from lib.local_config import OC_ROOT


def governed(repo: Path) -> str:
    """Why a repo is not governed, or an empty string when git runs its hooks."""
    if not (repo / ".git").exists():
        return f"{repo} is not a git repo"
    path = subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath"], capture_output=True, text=True).stdout.strip()
    hooks = (repo / path) if path and not os.path.isabs(path) else Path(path or "/nonexistent")
    if not (hooks / "pre-commit").is_file():
        return f"{repo} has no pre-commit hook that git runs (core.hooksPath is {path or 'unset'})"
    return ""


def command_job(argv: list[str]) -> int:
    """`olivercode job REPO -- COMMAND...`: run a scheduled agent job in a governed repo, and log a failed run."""
    if "--" not in argv or argv.index("--") != 1 or len(argv) < 3:
        print("Usage: olivercode job REPO -- COMMAND [ARGS...]")
        return 1
    repo = Path(argv[0]).expanduser().resolve()
    problem = governed(repo)
    if problem:
        print(f"Stopped: {problem}, so OliverCode does not govern it. Run `olivercode sync-hooks` for the fleet or `olivercode bootstrap` for a new repo.")
        return 1
    ran = subprocess.run(argv[2:], cwd=repo)
    if ran.returncode:
        failure_log.record("job", f"{' '.join(argv[2:3])} exited {ran.returncode}", repo.name)
    return ran.returncode
