"""Checkpoint a repo before an unattended run and restore it in one command.

`take` records the starting commit, the branch, the uncommitted tracked changes (kept as a commit
object under refs/olivercode/) and the untracked files present. `restore` returns the repo to that
state and removes the untracked files the run added. The record sits in ~/.olivercode/checkpoints,
outside every repo. Ignored files (caches, build output) are neither recorded nor removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _record_path(root: Path) -> Path:
    base = Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / "checkpoints"
    digest = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]
    return base / f"{root.name}-{digest}.json"


def _untracked(root: Path) -> list[str]:
    return [l for l in _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0") if l]


def take(root: Path) -> str:
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode:
        return f"Stopped: {root} has no commit to checkpoint."
    branch = _git(root, "branch", "--show-current").stdout.strip()
    stash = _git(root, "stash", "create").stdout.strip()
    if stash:
        _git(root, "update-ref", "refs/olivercode/checkpoint-stash", stash)
    _git(root, "update-ref", "refs/olivercode/checkpoint", head.stdout.strip())
    record = {"head": head.stdout.strip(), "branch": branch, "stash": stash, "untracked": _untracked(root),
              "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path = _record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    state = "with uncommitted changes saved" if stash else "clean"
    return f"Checkpoint of {root.name} at {record['head'][:9]} on {branch or 'a detached head'}, {state}, {len(record['untracked'])} untracked file(s) noted."


def restore(root: Path) -> str:
    path = _record_path(root)
    if not path.is_file():
        return f"Stopped: no checkpoint for {root.name}. Run `olivercode checkpoint {root}` first."
    rec = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    if rec["branch"] and _git(root, "branch", "--show-current").stdout.strip() != rec["branch"]:
        out = _git(root, "checkout", "-q", "-f", rec["branch"])
        if out.returncode:
            return f"Stopped: could not switch back to {rec['branch']}: {out.stderr.strip()[:120]}"
    reset = _git(root, "reset", "--hard", "-q", rec["head"])
    if reset.returncode:
        return f"Stopped: reset failed: {reset.stderr.strip()[:120]}"
    lines.append(f"Reset {root.name} to {rec['head'][:9]}.")
    kept = set(rec["untracked"])
    removed = []
    for rel in _untracked(root):
        if rel not in kept:
            target = root / rel
            target.unlink(missing_ok=True)
            removed.append(rel)
            parent = target.parent
            while parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    lines += [f"Removed {rel}" for rel in removed] or ["Removed no files."]
    if rec["stash"]:
        applied = _git(root, "stash", "apply", "-q", rec["stash"])
        lines.append("Reapplied the uncommitted changes." if not applied.returncode else f"Could not reapply the saved changes: {applied.stderr.strip()[:120]}")
    return "\n".join(lines)
