"""Process-safe account-wide Claude session slots and minimal session telemetry.

The lock is held around the actual CLI process. A process crash releases its flock,
so stale slot files do not strand capacity. Session logs contain metadata only, never prompts.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
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
    def __init__(self, fd: int, metadata: dict, story_fd: int | None = None):
        self.fd, self.metadata, self.finished, self.story_fd = fd, metadata, False, story_fd

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
        if self.story_fd is not None:
            try:
                fcntl.flock(self.story_fd, fcntl.LOCK_UN)
            finally:
                os.close(self.story_fd)

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


def story_spend(story: int, repo: str = "") -> float:
    """Cumulative priced model spend, including session telemetry and pre-telemetry rows."""
    prefix = f"story-{story}"
    total = 0.0
    sessions = failure_log.home() / LOG
    try:
        with sessions.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict) or row.get("event") != "session_end":
                    continue
                name = str(row.get("session") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                row_repo = str(row.get("repo") or "")
                repo_name = Path(repo).name
                if repo and row_repo and (row_repo != repo if "/" in row_repo or "/" in repo else row_repo != repo_name and not row_repo.startswith(repo_name + "-")):
                    continue
                cost = row.get("cost_usd")
                if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
                    total += float(cost)
    except OSError:
        pass
    path = failure_log.home() / "run-log.jsonl"
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue
                name = str(row.get("story") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                if repo and row.get("repo") and row.get("repo") != repo:
                    continue
                if row.get("session_id"):
                    continue
                cost = row.get("cost_usd")
                if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
                    total += float(cost)
    except OSError:
        pass
    return total


def story_attempts(story: int, repo: str = "") -> int:
    """Number of recorded model invocations for a story, including legacy rounds and API stops."""
    prefix = f"story-{story}"
    count = 0
    path = failure_log.home() / LOG
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict) or row.get("event") != "session_start":
                    continue
                name = str(row.get("session") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                row_repo = str(row.get("repo") or "")
                repo_name = Path(repo).name
                if repo and row_repo and (row_repo != repo if "/" in row_repo or "/" in repo else row_repo != repo_name and not row_repo.startswith(repo_name + "-")):
                    continue
                count += 1
    except OSError:
        pass
    legacy = failure_log.home() / "run-log.jsonl"
    try:
        with legacy.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict) or row.get("session_id"):
                    continue
                name = str(row.get("story") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                if repo and row.get("repo") and row.get("repo") != repo:
                    continue
                if "round" in row or row.get("stop") == "api_error":
                    count += 1
    except OSError:
        pass
    return count


def story_cost_unknown(story: int, repo: str = "") -> bool:
    """Unknown or corrupt cost history blocks another model session for this story."""
    path = failure_log.home() / "run-log.jsonl"
    prefix = f"story-{story}"
    if path.exists():
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        return True
                    if not isinstance(row, dict):
                        return True
                    name = str(row.get("story") or "")
                    if name != prefix and not name.startswith(prefix + "-"):
                        continue
                    if repo and row.get("repo") and row.get("repo") != repo:
                        continue
                    if "round" in row and row.get("cost_usd") is None:
                        return True
                    if row.get("stop") == "api_error" and row.get("cost_usd") is None:
                        return True
        except OSError:
            return True
    return story_has_unknown_cost(story, repo)


def acquire(session: str, model: str, cwd: str, session_id: str, resumed: bool = False, wait_seconds: float = 0.25, repo_slug: str = "") -> Lease:
    """Hold a shared account slot and a story-scoped lock while checking spend and running the CLI."""
    cap = max(1, local_config.max_builders())
    slot_dir = failure_log.home() / "model-session-slots"
    slot_dir.mkdir(parents=True, exist_ok=True)
    match = re.match(r"^story-(\d+)(?:-.+)?$", session)
    story_fd = None
    story = int(match.group(1)) if match else None
    if story is not None:
        repo_key = (repo_slug or Path(cwd).name).replace("/", "__")
        story_path = slot_dir / f"story-{repo_key}-{story}.lock"
        while True:
            story_fd = os.open(story_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(story_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                os.close(story_fd)
                time.sleep(wait_seconds)
        try:
            attempts = story_attempts(story, repo_slug)
            max_attempts = local_config.max_story_attempts()
            if attempts >= max_attempts:
                raise RuntimeError("Claude session refused: story #%d has reached its %d-session attempt ceiling." % (story, max_attempts))
            ceiling = local_config.max_story_spend()
            spent = story_spend(story, repo_slug)
            if story_cost_unknown(story, repo_slug):
                raise RuntimeError(f"Claude session refused: story #{story} has an unknown prior session cost; reconcile it before starting another session.")
            if spent >= ceiling:
                raise RuntimeError("Claude session refused: story #%d has spent $%.2f, reaching its $%.2f ceiling." % (story, spent, ceiling))
        except Exception:
            fcntl.flock(story_fd, fcntl.LOCK_UN)
            os.close(story_fd)
            story_fd = None
            raise
    try:
        while True:
            for n in range(cap):
                fd = os.open(slot_dir / f"slot-{n}.lock", os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    continue
                try:
                    started_epoch = time.time()
                    metadata = {"event": "session_start", "session": session, "session_id": session_id,
                                "model": model or "", "repo": repo_slug or Path(cwd).name, "started_at": _stamp(),
                                "slot": n, "cap": cap, "active_sessions": _active(slot_dir, cap),
                                "reason_started": ("independent review" if session.endswith("-review") else "repair session" if session.endswith("-fix") else "story builder" if session.startswith("story-") else "delegated model task"), "resumed": bool(resumed)}
                    if not _write_start(metadata):
                        raise RuntimeError("Claude session refused: durable session-start telemetry could not be written.")
                    lease = Lease(fd, metadata, story_fd)
                    lease.started_epoch = started_epoch
                    story_fd = None  # ownership transferred to the lease
                    return lease
                except Exception:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    raise
            time.sleep(wait_seconds)
    except Exception:
        if story_fd is not None:
            fcntl.flock(story_fd, fcntl.LOCK_UN)
            os.close(story_fd)
        raise


def story_has_unknown_cost(story: int, repo: str = "") -> bool:
    """Fail closed when any prior model invocation for this story lacks a priced completion."""
    prefix = f"story-{story}"
    starts: dict[str, int] = {}
    ends: dict[str, list[dict]] = {}
    path = failure_log.home() / LOG
    if not path.exists():
        return False
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    return True  # corruption makes the session/cost history incomplete
                if not isinstance(row, dict):
                    return True
                name = str(row.get("session") or "")
                if name != prefix and not name.startswith(prefix + "-"):
                    continue
                repo_name = Path(repo).name
                row_repo = str(row.get("repo") or "")
                if repo and row_repo and (row_repo != repo if "/" in row_repo or "/" in repo else row_repo != repo_name and not row_repo.startswith(repo_name + "-")):
                    continue
                sid = str(row.get("session_id") or "")
                if not sid:
                    return True
                if row.get("event") == "session_start":
                    starts[sid] = starts.get(sid, 0) + 1
                elif row.get("event") == "session_end":
                    ends.setdefault(sid, []).append(row)
    except OSError:
        return True
    for sid, count in starts.items():
        completions = ends.get(sid, [])
        if len(completions) < count:
            return True
        if any(not isinstance(row.get("cost_usd"), (int, float)) or isinstance(row.get("cost_usd"), bool) for row in completions):
            return True
    return False
