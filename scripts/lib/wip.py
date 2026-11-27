"""Work in progress snapshots: `olivercode wip save|list|restore`.

A restart or a crashed session loses whatever was never committed. `save` writes every dirty
tree under one repo (the repo itself and each of its worktrees) into a commit under
`refs/wip/<session-or-user>/<timestamp>`, built from a temporary index so the working tree, the
real index and every branch stay as they were. A clean tree makes no ref, a tree equal to the
session's last snapshot of it makes no new ref, and a repo holding an index.lock is skipped.
Each save prunes refs older than 7 days. `restore` checks a snapshot's changed files out into a
new folder and never writes into a working tree. Standard library only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PRUNE_DAYS = 7
NS = "refs/wip"
_IDENT = {"GIT_AUTHOR_NAME": "wip", "GIT_AUTHOR_EMAIL": "wip" + chr(64) + "olivercode.invalid",
          "GIT_COMMITTER_NAME": "wip", "GIT_COMMITTER_EMAIL": "wip" + chr(64) + "olivercode.invalid"}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _run(repo: Path, *args: str, env: dict | None = None, timeout: float = 20, check: bool = True) -> str:
    full = {**os.environ, **(env or {})}
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=full, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def label_for(session: str | None) -> str:
    """The ref folder name: the session id, or the user name, made safe for a ref."""
    raw = session or os.environ.get("USER") or "user"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")[:60] or "user"


def trees(start: Path) -> list[Path]:
    """The repo containing `start` and every worktree of it, or [] outside a repo."""
    try:
        top = Path(_run(start, "rev-parse", "--show-toplevel").strip())
        out = _run(top, "worktree", "list", "--porcelain")
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return []
    found = [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")]
    return [p for p in dict.fromkeys([top, *found]) if p.is_dir()]


def _stamp(now: float) -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(now))


def _snapshot(tree: Path, label: str, now: float, timeout: float, base: Path | None = None) -> str | None:
    """Make the ref for one tree and return its name, or None when there is nothing new to keep.

    The commit subject names the tree relative to `base` (the repo itself), so no machine path reaches a ref."""
    lock = Path(_run(tree, "rev-parse", "--path-format=absolute", "--git-path", "index.lock", timeout=timeout).strip())
    if lock.exists():
        return None
    head = _run(tree, "rev-parse", "-q", "--verify", "HEAD", check=False, timeout=timeout).strip()
    with tempfile.TemporaryDirectory(prefix="oc-wip-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if head:
            _run(tree, "read-tree", "HEAD", env=env, timeout=timeout)
        _run(tree, "add", "-A", env=env, timeout=timeout)
        tree_sha = _run(tree, "write-tree", env=env, timeout=timeout).strip()
    if tree_sha == (_run(tree, "rev-parse", "HEAD^{tree}", check=False, timeout=timeout).strip() if head else EMPTY_TREE):
        return None
    subject = f"wip {os.path.relpath(tree, base or tree)}"
    last = _run(tree, "for-each-ref", "--sort=-committerdate", "--count=50", f"{NS}/{label}/",
                "--format=%(tree) %(subject)", timeout=timeout).splitlines()
    for line in last:
        sha, _, subj = line.partition(" ")
        if subj == subject:
            if sha == tree_sha:
                return None
            break
    args = ["commit-tree", tree_sha, "-m", subject]
    if head:
        args += ["-p", head]
    when = f"{int(now)} +0000"
    commit = _run(tree, *args, env={**_IDENT, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}, timeout=timeout).strip()
    ref = f"{NS}/{label}/{_stamp(now)}"
    n = 1
    while _run(tree, "rev-parse", "-q", "--verify", ref, check=False, timeout=timeout).strip():
        n += 1
        ref = f"{NS}/{label}/{_stamp(now)}-{n}"
    _run(tree, "update-ref", ref, commit, timeout=timeout)
    return ref


def prune(repo: Path, now: float | None = None, timeout: float = 20) -> list[str]:
    """Delete the wip refs older than PRUNE_DAYS and return their names."""
    cutoff = (now or time.time()) - PRUNE_DAYS * 86400
    gone = []
    for line in _run(repo, "for-each-ref", NS, "--format=%(refname) %(committerdate:unix)", timeout=timeout).splitlines():
        ref, _, stamp = line.rpartition(" ")
        if stamp.isdigit() and int(stamp) < cutoff:
            _run(repo, "update-ref", "-d", ref, timeout=timeout)
            gone.append(ref)
    return gone


def save(start: Path, session: str | None = None, now: float | None = None, budget: float | None = None,
         say: bool = True) -> list[str]:
    """Snapshot every dirty tree of the repo containing `start`. Returns the refs made.

    `budget` is the seconds the whole call may take; a tree not reached by then is left for the next save.
    """
    start_time = time.monotonic()
    when = now if now is not None else time.time()
    label = label_for(session)
    made: list[str] = []
    all_trees = trees(start)
    for tree in all_trees:
        left = None if budget is None else budget - (time.monotonic() - start_time)
        if left is not None and left <= 0:
            print(f"wip save: out of time, skipped {tree}", file=sys.stderr)
            continue
        try:
            ref = _snapshot(tree, label, when, left or 20, all_trees[0])
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"wip save: skipped {tree}: {exc}", file=sys.stderr)
            continue
        if ref:
            made.append(ref)
            if say:
                print(f"saved {tree} -> {ref}")
    if all_trees:
        try:
            prune(all_trees[0], now, timeout=5)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"wip save: prune skipped: {exc}", file=sys.stderr)
    return made


def _files(repo: Path, ref: str, parents: list[str] | None = None) -> list[str]:
    """The files a snapshot changed or added against the commit it was made on. A caller that already knows the parents passes them."""
    if parents is None:
        parents = _run(repo, "rev-list", "--parents", "-n", "1", ref).split()[1:]
    args = ["diff-tree", "-r", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z"]
    args += [parents[0], ref] if parents else ["--root", ref]
    return [f for f in _run(repo, *args).split("\0") if f]


def listing(start: Path) -> list[str]:
    """One line per snapshot: repo, time and changed file count, newest first."""
    top = trees(start)
    if not top:
        return []
    rows = []
    for line in _run(top[0], "for-each-ref", NS, "--sort=-committerdate",
                     "--format=%(refname)%09%(committerdate:unix)%09%(parent)%09%(subject)").splitlines():
        ref, stamp, parent, subject = line.split("\t", 3)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(stamp)))
        rows.append(f"{ref}  {subject.removeprefix('wip ')}  {when}  {len(_files(top[0], ref, parent.split()))} files")
    return rows


def restore(start: Path, ref: str, target: Path | None = None) -> Path:
    """Check a snapshot's changed files out into `target` (a new folder by default) and return it."""
    top = trees(start)
    if not top:
        raise ValueError(f"{start} is not in a git repo")
    repo = top[0]
    full = ref if ref.startswith("refs/") else f"{NS}/{ref}"
    sha = _run(repo, "rev-parse", "-q", "--verify", f"{full}^{{commit}}", check=False).strip() \
        or _run(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False).strip()
    if not sha:
        raise ValueError(f"no snapshot named {ref}; `olivercode wip list` shows them")
    if target is None:
        base = Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / "wip-restore"
        target = base / f"{repo.name}-{ref.rstrip('/').rsplit('/', 1)[-1]}"
    target = Path(target).expanduser().resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"{target} already holds files; pick a new folder with --to")
    if any(target == t or t in target.parents for t in top):
        raise ValueError(f"{target} is inside a working tree; pick a folder outside it with --to")
    files = _files(repo, sha)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oc-wip-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _run(repo, "read-tree", sha, env=env)
        subprocess.run(["git", "-C", str(repo), "checkout-index", "-f", f"--prefix={target}/", "-z", "--stdin"],
                       input="\0".join(files) + "\0" if files else "", text=True, capture_output=True, check=True,
                       env={**os.environ, **env})
    return target


def command_wip(argv: list[str], cwd: Path | None = None) -> int:
    """`olivercode wip save [--session ID] | list | restore REF [--to DIR]`."""
    here = Path(cwd or Path.cwd())
    usage = "Usage: olivercode wip save [--session ID] | list | restore REF [--to DIR]"
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    try:
        if cmd == "save":
            session = None
            if rest[:1] == ["--session"] and len(rest) == 2:
                session = rest[1]
            elif rest:
                print(usage)
                return 1
            made = save(here, session)
            print(f"{len(made)} snapshot(s) saved" if made else "Nothing to save: every tree is clean or already saved.")
            return 0
        if cmd == "list" and not rest:
            rows = listing(here)
            print("\n".join(rows) if rows else "No snapshots.")
            return 0
        if cmd == "restore" and rest and not rest[0].startswith("-"):
            target = None
            if rest[1:2] == ["--to"] and len(rest) == 3:
                target = Path(rest[2])
            elif len(rest) > 1:
                print(usage)
                return 1
            out = restore(here, rest[0], target)
            print(f"Restored into {out}. Your working tree was not touched.")
            return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}")
        return 1
    print(usage)
    return 1
