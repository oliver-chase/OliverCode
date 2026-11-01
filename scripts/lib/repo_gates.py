"""Whether git will actually run a repo's commit gates.

A repo that ships `.githooks/pre-commit` is only protected while `core.hooksPath` points
at a directory holding an executable `pre-commit`. When it does not, git runs no hooks
and says nothing, so a commit with a secret in it goes straight through. The Claude Code
hooks in `scripts/hooks/` call this at session start and before every `git commit`, so
the fail-open is caught in the session that would commit, in any repo, registered or not.

Standard library only: these checks run inside a hook on every Bash call.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def repo_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def hooks_path(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def has_gates(root: Path) -> bool:
    """The repo ships its own commit gates."""
    return (root / ".githooks" / "pre-commit").is_file()


def gate_problem(root: Path) -> str:
    """Why git would skip this repo's gates, or "" when they run. Only for a repo with gates."""
    configured = hooks_path(root)
    if not configured:
        return "core.hooksPath is unset, so git runs none of this repo's commit gates"
    hooks_dir = Path(configured).expanduser()
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    if not hooks_dir.is_dir():
        return f"core.hooksPath points at {configured}, which does not exist, so git runs no hooks"
    live = hooks_dir / "pre-commit"
    if not live.is_file():
        return f"{configured} holds no pre-commit file, so git runs no hooks"
    if not os.access(live, os.X_OK):
        return f"{configured}/pre-commit is not executable, so git skips it"
    return ""
