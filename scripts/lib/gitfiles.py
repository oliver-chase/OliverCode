"""One reader of `git ls-files`, for the checks that list a repo's files."""
from __future__ import annotations

import subprocess
from pathlib import Path


def tracked_files(repo_root: Path, *args: str) -> list[str]:
    """The paths `git ls-files ARGS` prints for the repo, or an empty list when git fails."""
    out = subprocess.run(["git", "-C", str(repo_root), "ls-files", *args], capture_output=True, text=True, check=False)
    return [line for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []
