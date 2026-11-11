"""One home for repos: every checkout, worktree and backup lives under repoRoot.

`olivercode.local.json` names the root (`repoRoot`, default the folder that holds OliverCode),
the folders to scan for strays (`watchRoots`, default ~/Developer, ~/Desktop and ~/Documents)
and the checkouts allowed to stay elsewhere (`allowOutside`). Worktrees live in
`<repoRoot>/_worktrees` and backups in `<repoRoot>/_archive`.

`health`, `place` and the session-start hook read findings from here, `placement_guard.py`
refuses a new clone or worktree outside the root, and `clean` removes what is reclaimable.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lib.local_config import OC_ROOT, load_local

SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
BACKUP_NAME = re.compile(r"(backup|\.bak$|-old$|-copy$)", re.IGNORECASE)
MAX_DEPTH = 3


@dataclass
class Config:
    root: Path
    worktrees: Path
    archive: Path
    watch: list
    allow: list


@dataclass
class Finding:
    kind: str  # repo, worktree, backup, broken-link
    path: Path
    fix: str


def _p(value: str) -> Path:
    return Path(value).expanduser()


def config() -> Config:
    local = load_local()
    root = _p(local["repoRoot"]) if local.get("repoRoot") else OC_ROOT.parent
    home = Path.home()
    watch = [_p(w) for w in local["watchRoots"]] if "watchRoots" in local else [home / "Developer", home / "Desktop", home / "Documents"]
    return Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive",
                  watch=watch, allow=[_p(a) for a in local.get("allowOutside", [])])


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_worktree(path: Path) -> bool:
    """A linked worktree has a `.git` file that points into the owner's .git/worktrees."""
    git = path / ".git"
    if not git.is_file():
        return False
    try:
        return "/worktrees/" in git.read_text(errors="ignore")
    except OSError:
        return False


def checkouts(base: Path, depth: int = MAX_DEPTH):
    """Yield every folder under base (to `depth`) that holds a `.git`, without descending into one."""
    if not base.is_dir():
        return
    base_depth = len(base.parts)
    for here, dirs, _ in os.walk(base):
        here_path = Path(here)
        if (here_path / ".git").exists():
            dirs[:] = []
            yield here_path
            continue
        if len(here_path.parts) - base_depth >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (here_path / d).is_symlink()]


def _git(path: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout)


def linked_worktrees(cfg: Config) -> list[tuple[Path, Path]]:
    """(worktree, owning repo) for every linked worktree git knows about, wherever it sits (including /tmp)."""
    found = []
    if not cfg.root.is_dir():
        return found
    for repo in sorted(cfg.root.iterdir()):
        if repo.name.startswith("_") or not (repo / ".git").is_dir():
            continue
        try:
            out = _git(repo, "worktree", "list", "--porcelain").stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = Path(line[9:])
                if path.resolve() != repo.resolve():
                    found.append((path, repo))
    return found


def findings(cfg: Config | None = None) -> list[Finding]:
    """Everything out of place: repos and worktrees outside the root, worktrees outside _worktrees, backups and broken links."""
    cfg = cfg or config()
    out: list[Finding] = []
    seen: set[Path] = set()
    for base in cfg.watch:
        for repo in checkouts(base):
            real = repo.resolve()
            if real in seen or inside(repo, cfg.root) or any(inside(repo, a) or repo.resolve() == a.resolve() for a in cfg.allow):
                continue
            seen.add(real)
            if is_worktree(repo):
                out.append(Finding("worktree", repo, f"move it to {cfg.worktrees}/{repo.name}"))
            else:
                out.append(Finding("repo", repo, f"move it to {cfg.root}/{repo.name}"))
    if cfg.root.is_dir():
        for child in sorted(cfg.root.iterdir()):
            if child.name.startswith("_"):
                continue
            if child.is_symlink() and not child.exists():
                out.append(Finding("broken-link", child, "remove the dead link"))
            elif child.is_symlink():
                out.append(Finding("repo", child, f"replace the link with the real folder {child.resolve()}"))
            elif is_worktree(child):
                out.append(Finding("worktree", child, f"move it to {cfg.worktrees}/{child.name}"))
            elif BACKUP_NAME.search(child.name):
                out.append(Finding("backup", child, f"move it to {cfg.archive}/{child.name}"))
    for path, repo in linked_worktrees(cfg):
        if path.resolve() not in seen and not inside(path, cfg.worktrees) and not any(f.path == path for f in out):
            out.append(Finding("worktree", path, f"move it with `git -C {repo} worktree move {path} {cfg.worktrees}/{path.name}`"))
    if cfg.worktrees.is_dir():
        for child in sorted(cfg.worktrees.iterdir()):
            if not child.name.startswith(".") and not is_worktree(child):
                out.append(Finding("repo", child, "only linked worktrees belong in _worktrees"))
    return out


@dataclass
class Worktree:
    path: Path
    branch: str
    dirty: bool
    merged: bool
    common: Path


def worktrees(cfg: Config | None = None) -> list[Worktree]:
    """Every linked worktree under the root, the watched folders or _worktrees, with its merge and dirty state."""
    cfg = cfg or config()
    found = []
    seen: set[Path] = set()
    candidates = [path for path, _ in linked_worktrees(cfg)]
    for base in cfg.watch:
        candidates += [r for r in checkouts(base) if is_worktree(r)]
    if True:
        for repo in candidates:
            if repo.resolve() in seen or not repo.is_dir():
                continue
            seen.add(repo.resolve())
            try:
                dirty = bool(_git(repo, "status", "--short").stdout.strip())
                merged = _git(repo, "merge-base", "--is-ancestor", "HEAD", "origin/main").returncode == 0
                common = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip()).resolve().parent
                branch = _git(repo, "branch", "--show-current").stdout.strip()
            except (OSError, subprocess.SubprocessError):
                continue
            found.append(Worktree(repo, branch, dirty, merged, common))
    return found


def clean(cfg: Config | None = None, apply: bool = False) -> list[str]:
    """Lines saying what happens to each worktree: merged and clean ones are removed, the rest kept and why."""
    lines = []
    for wt in worktrees(cfg):
        if wt.dirty:
            lines.append(f"KEEP   {wt.path} (uncommitted changes)")
        elif not wt.merged:
            lines.append(f"KEEP   {wt.path} (branch {wt.branch or 'detached'} has commits not on origin/main)")
        elif apply:
            done = _git(wt.common, "worktree", "remove", str(wt.path))
            lines.append(f"REMOVE {wt.path}" if done.returncode == 0 else f"FAILED {wt.path}: {done.stderr.strip()[:80]}")
        else:
            lines.append(f"REMOVE {wt.path} (merged and clean; run with --apply)")
    return lines


# --- the creation gate -------------------------------------------------------------------------

_VALUE_OPTIONS_ADD = {"-b", "-B", "--reason"}
_VALUE_OPTIONS_CLONE = {"-b", "--branch", "--depth", "-o", "--origin", "--reference", "--separate-git-dir",
                        "--template", "-c", "--config", "-j", "--jobs", "--filter", "-u", "--upload-pack", "--shallow-since"}


def violation(command_words: list[str], cwd: Path, cfg: Config | None = None) -> str:
    """The refusal text when `git worktree add` or `git clone` would create a checkout outside its home, or ''."""
    cfg = cfg or config()
    words = list(command_words)
    if "git" not in words:
        return ""
    rest = words[words.index("git") + 1:]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
    if rest[:2] == ["worktree", "add"]:
        args, skip, positional = rest[2:], False, []
        for a in args:
            if skip:
                skip = False
            elif a in _VALUE_OPTIONS_ADD:
                skip = True
            elif not a.startswith("-"):
                positional.append(a)
        if not positional:
            return ""
        dest = (cwd / _p(positional[0])).resolve()
        if not inside(dest, cfg.worktrees):
            return (f"Worktrees live under {cfg.worktrees}. Use `git worktree add {cfg.worktrees}/{dest.name} ...` "
                    f"instead of {dest}.")
    elif rest[:1] == ["clone"]:
        args, skip, positional = rest[1:], False, []
        for a in args:
            if skip:
                skip = False
            elif a in _VALUE_OPTIONS_CLONE:
                skip = True
            elif not a.startswith("-"):
                positional.append(a)
        if not positional:
            return ""
        name = re.sub(r"\.git$", "", positional[0].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
        dest = (cwd / _p(positional[1])).resolve() if len(positional) > 1 else (cwd / name).resolve()
        if not inside(dest, cfg.root):
            return f"Repos live under {cfg.root}. Clone into {cfg.root}/{dest.name} instead of {dest}."
    return ""


def split(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=False)
    except ValueError:
        return []
