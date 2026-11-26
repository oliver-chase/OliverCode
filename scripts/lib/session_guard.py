"""Process-safe account-wide Claude session slots and minimal session telemetry.

The lock is held around the actual CLI process. A process crash releases its flock,
so stale slot files do not strand capacity. Session logs contain metadata only, never prompts.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, local_config

LOG = "model-sessions.jsonl"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(row: dict) -> bool:
    path = failure_log.home() / LOG
    try:
        with failure_log.locked(path):
            failure_log.append_private(path, json.dumps(row, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def _active(slot_dir: Path, cap: int) -> int:
    count = 0
    for n in range(cap):
        path = slot_dir / f"slot-{n}.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                count += 1
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return count


class Lease:
    def __init__(self, fd: int, metadata: dict):
        self.fd, self.metadata, self.finished = fd, metadata, False

    def finish(self, details: dict | None = None) -> None:
        if self.finished:
            return
        details = details or {}
        self.finished = True
        _write({**self.metadata, "event": "session_end", "ended_at": _stamp(),
                "duration_s": round(max(0, time.time() - self.started_epoch), 3),
                "stop_reason": details.get("stop_reason", "unknown"),
                "exit_code": details.get("exit_code"),
                "usage": details.get("usage"),
                "tokens": details.get("tokens"),
                "cost_usd": details.get("cost_usd"),
                "resumed": details.get("resumed", self.metadata.get("resumed", False))})

    def release(self) -> None:
        if not self.finished:
            self.finish({"stop_reason": "exception_or_unrecorded_exit"})
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def _write_start(row: dict) -> bool:
    """Atomically assign an invocation number and persist its start record."""
    path = failure_log.home() / LOG
    try:
        with failure_log.locked(path):
            count = 0
            if path.is_file():
                with path.open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            previous = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(previous, dict) and previous.get("event") == "session_start" and previous.get("session") == row.get("session"):
                            count += 1
            row["attempt"] = count + 1
            failure_log.append_private(path, json.dumps(row, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def acquire(session: str, model: str, cwd: str, session_id: str, resumed: bool = False, wait_seconds: float = 0.25) -> Lease:
    """Wait for and hold one shared account slot; configured maxBuilders is the hard session cap."""
    cap = max(1, local_config.max_builders())
    slot_dir = failure_log.home() / "model-session-slots"
    slot_dir.mkdir(parents=True, exist_ok=True)
    while True:
        for n in range(cap):
            path = slot_dir / f"slot-{n}.lock"
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            started_epoch = time.time()
            metadata = {"event": "session_start", "session": session, "session_id": session_id,
                        "model": model or "", "repo": Path(cwd).name, "started_at": _stamp(),
                        "slot": n, "cap": cap, "active_sessions": _active(slot_dir, cap),
                        "reason_started": ("independent review" if session.endswith("-review") else "repair session" if session.endswith("-fix") else "story builder" if session.startswith("story-") else "delegated model task"), "resumed": bool(resumed)}
            if not _write_start(metadata):
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                raise RuntimeError("Claude session refused: durable session-start telemetry could not be written.")
            lease = Lease(fd, metadata)
            lease.started_epoch = started_epoch
            return lease
        time.sleep(wait_seconds)


def story_has_unknown_cost(story: int, repo: str = "") -> bool:
    """Fail closed when any prior model invocation for this story lacks a priced completion."""
    prefix = f"story-{story}"
    starts: dict[str, int] = {}
    ends: dict[str, list[dict]] = {}
    path = failure_log.home() / LOG
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue
                name = str(row.get("session") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                repo_name = Path(repo).name
                if repo and row.get("repo") and row.get("repo") != repo_name and not row.get("repo", "").startswith(repo_name + "-"):
                    continue
                sid = str(row.get("session_id") or "")
                if not sid:
                    continue
                if row.get("event") == "session_start":
                    starts[sid] = starts.get(sid, 0) + 1
                elif row.get("event") == "session_end":
                    ends.setdefault(sid, []).append(row)
    except OSError:
        return False
    for sid, count in starts.items():
        completions = ends.get(sid, [])
        if len(completions) < count:
            return True
        if any(not isinstance(row.get("cost_usd"), (int, float)) or isinstance(row.get("cost_usd"), bool) for row in completions):
            return True
    return False
