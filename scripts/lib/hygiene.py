"""Repo hygiene checks `olivercode maintain` runs across every repo under repoRoot.

Three checks, all pure Python so they run the same on any machine:

- sync-conflict copies: a sync tool or Finder leaves "name 2.ext" beside "name.ext" when two writers collide.
  A byte-identical copy is deleted, a differing copy older than its original moves to `<repoRoot>/_archive/stray-copies`,
  and a differing copy newer than its original is left for the owner.
- git data inside a synced folder: `.git` moves to `.git.nosync` (sync services skip that suffix) and a symlink keeps
  git working, so a sync tool can never evict, duplicate or half-sync the object store.
- docs that trail the code: a tracked document that names a file which changed long after the document did.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

COPY_NAME = re.compile(r"^(?P<stem>.+?) (?P<n>\d+)(?P<ext>\.[^./ ]+)?$")
SYNC_MARKERS = ("Mobile Documents", "CloudStorage", "Dropbox", "OneDrive", "Google Drive", "GoogleDrive", "iCloud")
STALE_DAYS = 60
MAX_STALE_PER_REPO = 5
BACKTICK = re.compile(r"`([^`\s]+)`")


@dataclass
class Copy:
    path: Path
    original: Path
    verdict: str  # identical, older, newer


SF_DATALESS = 0x40000000  # macOS: the file's content lives in the cloud and reading it blocks on a download


def evicted(path: Path) -> bool:
    """True when a sync service evicted the file. Every check here skips such files, since reading one blocks."""
    try:
        return bool(getattr(os.stat(path), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return True


def _git(repo: Path, *args: str) -> str:
    """git's output, or '' when it fails or takes over a minute, so one slow repo never stops a whole run."""
    try:
        ran = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return ran.stdout if ran.returncode == 0 else ""


def original_of(rel: str) -> str | None:
    """The path a numbered copy was made from, or None when the name is not a copy name."""
    parent, _, name = rel.rpartition("/")
    m = COPY_NAME.match(name)
    if not m:
        return None
    original = m.group("stem") + (m.group("ext") or "")
    return f"{parent}/{original}" if parent else original


def stray_copies(repo: Path) -> list[Copy]:
    """Untracked numbered copies whose original exists, each judged against that original."""
    found = []
    for rel in _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        original = original_of(rel) if rel else None
        path, source = repo / rel, repo / (original or "")
        if not original or not path.is_file() or not source.is_file():
            continue
        if evicted(path) or evicted(source):
            verdict = "newer"  # unreadable without a download, so it stays for the owner
        elif path.read_bytes() == source.read_bytes():
            verdict = "identical"
        else:
            verdict = "older" if path.stat().st_mtime <= source.stat().st_mtime else "newer"
        found.append(Copy(path, source, verdict))
    return found


def clear_copies(repo: Path, archive: Path, copies: list[Copy]) -> int:
    """Delete identical copies and archive older ones. Returns how many were cleared. A newer copy stays."""
    cleared = 0
    for c in copies:
        if c.verdict == "identical":
            c.path.unlink()
        elif c.verdict == "older":
            dest = archive / "stray-copies" / repo.name / c.path.relative_to(repo)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(c.path), str(dest))
        else:
            continue
        cleared += 1
    return cleared


def synced_marker(root: Path, home: Path | None = None) -> str:
    """Name of the sync service that mirrors `root`, or ''. macOS mirrors Desktop and Documents into iCloud Drive."""
    home = home or Path.home()
    resolved = str(root.resolve())
    for marker in SYNC_MARKERS:
        if marker in resolved:
            return marker
    cloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    for folder in ("Desktop", "Documents"):
        if (cloud / folder).is_dir():
            try:
                root.resolve().relative_to((home / folder).resolve())
                return "iCloud Desktop & Documents"
            except ValueError:
                continue
    return ""


NOSYNC = ".git.nosync"


EXCLUDE_LINE = "/" + NOSYNC


def _excluded(repo: Path) -> bool:
    exclude = repo / NOSYNC / "info" / "exclude"
    return exclude.is_file() and EXCLUDE_LINE in exclude.read_text(errors="ignore").splitlines()


def _exclude(repo: Path) -> None:
    """Tell git to ignore `.git.nosync`, which it would otherwise list as untracked content for `git add .` to pick up."""
    exclude = repo / NOSYNC / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        f.write(("" if not exclude.stat().st_size or exclude.read_text().endswith("\n") else "\n") + EXCLUDE_LINE + "\n")


def _link_copies(repo: Path) -> list[Path]:
    """Copies of the `.git` link that a sync service made, such as ".git 2"."""
    return [c for c in repo.glob(".git [0-9]*") if c.is_symlink() and os.readlink(c) == NOSYNC]


def _stray_git_dirs(repo: Path) -> list[Path]:
    """`.git N` folders a sync service left beside the link: small ones that hold no object store, refs or hooks."""
    found = []
    for c in repo.glob(".git [0-9]*"):
        if not c.is_dir() or c.is_symlink():
            continue
        inside = list(c.rglob("*"))
        size = sum(p.stat().st_size for p in inside if p.is_file() and not p.is_symlink())
        if not any(p.name in ("objects", "refs", "hooks") for p in inside) and size < 1_000_000:
            found.append(c)
    return found


def _clear_strays(repo: Path, archive: Path | None) -> None:
    """Drop the link copies and the empty stray folders. A stray folder holding files moves to the archive, or stays."""
    for copy in _link_copies(repo):
        copy.unlink()
    for folder in _stray_git_dirs(repo):
        if not any(p.is_file() or p.is_symlink() for p in folder.rglob("*")):
            shutil.rmtree(folder)
        elif archive is not None:
            dest = archive / "stray-copies" / repo.name / folder.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(dest))


def git_protected(repo: Path) -> bool:
    """True when `.git` is a symlink to a `.git.nosync` folder that git ignores, with no sync copies left beside it."""
    return ((repo / ".git").is_symlink() and (repo / NOSYNC).is_dir() and _excluded(repo)
            and not _link_copies(repo) and not _stray_git_dirs(repo))


def protect_git(repo: Path, archive: Path | None = None) -> str:
    """Move `.git` to `.git.nosync`, link it back and make git ignore it. Returns '' on success, else why nothing changed.
    Copies a sync service left beside the link are cleared, and `archive` receives any that hold files."""
    git, nosync = repo / ".git", repo / NOSYNC
    if nosync.is_dir() and not git.exists() and not git.is_symlink():
        # a sync service renamed the link to ".git 2": drop those copies and link again
        _clear_strays(repo, archive)
        git.symlink_to(NOSYNC)
        if not _excluded(repo):
            _exclude(repo)
        return "" if _git(repo, "rev-parse", "--git-dir").strip() else "git did not work through the restored link"
    if git.is_symlink() and nosync.is_dir():
        _clear_strays(repo, archive)
        if not _excluded(repo):
            _exclude(repo)
        return ""
    if git.is_symlink() or not git.is_dir():
        return "not a plain .git folder"
    if nosync.exists():
        return f"{NOSYNC} already exists"
    if any(git.glob("*.lock")):
        return "a git operation is running (lock file in .git)"
    git.rename(nosync)
    git.symlink_to(NOSYNC)
    if _git(repo, "rev-parse", "--git-dir").strip():
        _exclude(repo)
        return ""
    git.unlink()
    nosync.rename(git)
    return "git did not work through the link, so it was undone"


def last_changed(repo: Path) -> dict[str, int]:
    """Commit time of each tracked path's latest change, from one `git log` pass."""
    times: dict[str, int] = {}
    stamp = 0
    for line in _git(repo, "log", "--name-only", "--format=@%ct", "--no-renames").splitlines():
        if line.startswith("@"):
            stamp = int(line[1:])
        elif line and line not in times:
            times[line] = stamp
    return times


def stale_docs(repo: Path, days: int = STALE_DAYS) -> list[str]:
    """`doc names file (changed N days after it)` for each root or docs/ markdown file that trails a file it names."""
    times = last_changed(repo)
    out = []
    for doc in sorted(p for p in times if p.endswith(".md") and p.count("/") <= 1 and (p.startswith("docs/") or "/" not in p)):
        if not (repo / doc).is_file() or evicted(repo / doc):
            continue
        newest, newest_path = 0, ""
        for ref in BACKTICK.findall((repo / doc).read_text(errors="ignore")):
            ref = ref.rstrip(".,;:").split("#")[0]
            if ref != doc and ref in times and not ref.endswith(".md") and times[ref] > newest:
                newest, newest_path = times[ref], ref
        gap = (newest - times[doc]) // 86400 if newest else 0
        if gap > days:
            out.append(f"{doc} names {newest_path}, which changed {gap} days after it")
    return out[:MAX_STALE_PER_REPO]
