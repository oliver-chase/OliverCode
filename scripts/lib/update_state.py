"""The checks `olivercode update` makes before it pulls. Each refusal names the one command that fixes it.

Only a change to a tracked file makes the checkout dirty. A per-user file the checkout keeps untracked or ignored,
such as olivercode.local.json or docs/LESSONS.jsonl, never blocks an update unless the release adds a file at the
same path. Every fix runs without write access to origin, so a user who cannot push is never told to push (#762).
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

LOCAL_BRANCH = "olivercode-local"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _git_path(root: Path, name: str) -> Path:
    out = Path(_git(root, "rev-parse", "--git-path", name).stdout.strip())
    return out if out.is_absolute() else root / out


def _lines(proc: subprocess.CompletedProcess) -> set[str]:
    return {line for line in proc.stdout.splitlines() if line.strip()}


def _free_branch(root: Path) -> str:
    """The first olivercode-local branch name this checkout does not use yet."""
    name, n = LOCAL_BRANCH, 1
    while _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0:
        n += 1
        name = f"{LOCAL_BRANCH}-{n}"
    return name


def ahead_commits(root: Path) -> list[str]:
    """One line per commit this checkout holds that origin/main lacks, as `SHA AUTHOR: subject`. Empty when there are none or origin is unknown (#785)."""
    out = _git(root, "log", "--format=%h %an: %s", "origin/main..HEAD")
    return [line for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []


def ahead_fix(root: Path) -> str:
    """The one command that moves this checkout's local commits to a branch and leaves it level with origin/main. It needs no write access to origin (#785)."""
    q = shlex.quote(str(root))
    return f"git -C {q} branch {_free_branch(root)} && git -C {q} reset --keep origin/main"


def problem(root: Path) -> tuple[str, str] | None:
    """(what is wrong, the one command that fixes it), or None when the checkout can fast-forward."""
    q = shlex.quote(str(root))
    if _git_path(root, "rebase-merge").exists() or _git_path(root, "rebase-apply").exists():
        return ("a rebase is in progress", f"git -C {q} rebase --abort")
    if _git_path(root, "MERGE_HEAD").exists():
        return ("a merge is in progress", f"git -C {q} merge --abort")
    if _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return ("the checkout has uncommitted changes to tracked files",
                f"git -C {q} stash push -m 'before olivercode update'")
    if _git(root, "rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        return ("this branch has no upstream to pull from", f"git -C {q} branch --set-upstream-to=origin/main")
    if _git(root, "fetch", "--quiet").returncode != 0:
        return ("could not fetch from origin", f"git -C {q} fetch")
    behind = int(_git(root, "rev-list", "--count", "HEAD..@{u}").stdout.strip() or 0)
    held = ahead_commits(root)
    if held:  # a checkout that holds commits origin lacks is refused, and the fix moves them to a branch (#785)
        more = f", and origin has {behind} more" if behind else ""
        return (f"{len(held)} commit(s) on this checkout are not on origin{more}: {'; '.join(held)}. The fix keeps them on a local branch, "
                "needs no write access to origin, and leaves the checkout level with origin/main", ahead_fix(root))
    incoming = _lines(_git(root, "diff", "--name-only", "HEAD", "@{u}")) if behind else set()
    blocked = sorted(incoming & _lines(_git(root, "ls-files", "--others", "--exclude-standard")))
    if blocked:
        paths = " ".join(shlex.quote(p) for p in blocked)
        return (f"the release adds {', '.join(blocked)}, which this checkout already holds as an untracked file",
                f"git -C {q} stash push --include-untracked -m 'before olivercode update' -- {paths}")
    return None

