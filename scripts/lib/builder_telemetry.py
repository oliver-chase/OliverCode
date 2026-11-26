"""Durable, privacy-minimal builder lifecycle events and deterministic concurrency summaries.

The event log complements model-sessions.jsonl: this file records story workers,
while the session log records individual Claude CLI invocations. It stores metadata
only, never prompts, transcripts, or environment values.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log

LOG = "builder-events.jsonl"


def _epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def record(event: str, repo: str, *, story: int | None = None, run_id: str = "", worker_id: str = "",
           claim_id: str = "", **fields) -> bool:
    """Append one versioned lifecycle event. Logging failure never interrupts delivery."""
    row = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "event": event,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": repo,
    }
    if story is not None:
        row["story"] = int(story)
    if run_id:
        row["run_id"] = run_id
    if worker_id:
        row["worker_id"] = worker_id
    if claim_id:
        row["claim_id"] = claim_id
    row.update({key: value for key, value in fields.items() if value is not None})
    path = failure_log.home() / LOG
    try:
        with failure_log.locked(path):
            failure_log.append_private(path, json.dumps(row, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def read(path: Path | None = None) -> tuple[list[dict], int]:
    """Return valid event rows and the number of malformed lines."""
    target = path or failure_log.home() / LOG
    rows, malformed = [], 0
    try:
        with target.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    malformed += 1
                    continue
                if not isinstance(row, dict) or not row.get("event") or not row.get("at"):
                    malformed += 1
                    continue
                rows.append(row)
    except FileNotFoundError:
        pass
    except OSError:
        malformed += 1
    return rows, malformed


def summarize(hours: float = 24, now: float | None = None, path: Path | None = None) -> dict:
    """Summarize complete worker intervals; unmatched starts are reported, never guessed to still be active."""
    now = time.time() if now is None else float(now)
    window = max(0.0, float(hours)) * 3600
    start_window = now - window
    rows, malformed = read(path)
    rows.sort(key=lambda row: _epoch(row.get("at")) or 0)
    starts: dict[str, dict] = {}
    claims: dict[str, float] = {}
    intervals: list[tuple[float, float]] = []
    queue_waits: list[float] = []
    completed = failed = 0
    unmatched_ends = 0
    for row in rows:
        at = _epoch(row.get("at"))
        if at is None:
            malformed += 1
            continue
        event = row.get("event")
        if event == "story_claimed" and row.get("claim_id"):
            claims[str(row["claim_id"])] = at
        elif event == "builder_started":
            worker = str(row.get("worker_id") or row.get("event_id") or "")
            if worker:
                starts[worker] = row
                claimed = claims.get(str(row.get("claim_id") or ""))
                if claimed is not None and at >= claimed:
                    queue_waits.append(at - claimed)
        elif event == "builder_finished":
            worker = str(row.get("worker_id") or "")
            began = starts.pop(worker, None)
            if began is None:
                unmatched_ends += 1
                continue
            began_at = _epoch(began.get("at"))
            if began_at is None or at < began_at:
                malformed += 1
                continue
            intervals.append((began_at, at))
            if row.get("outcome") == "landed":
                completed += 1
            else:
                failed += 1

    clipped = [(max(a, start_window), min(b, now)) for a, b in intervals if b >= start_window and a <= now]
    clipped = [(a, b) for a, b in clipped if b > a]
    duration = sum(b - a for a, b in clipped)
    average = duration / window if window > 0 and clipped else None
    points = []
    for a, b in clipped:
        points.extend(((a, 1), (b, -1)))
    active = peak = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    recent_starts = sum(1 for row in rows if row.get("event") == "builder_started"
                        and start_window <= (_epoch(row.get("at")) or 0) <= now)
    return {
        "hours": float(hours),
        "builder_starts": recent_starts,
        "completed": completed,
        "not_landed": failed,
        "average_active": average,
        "peak_active": peak if clipped else None,
        "average_queue_wait_s": (sum(queue_waits) / len(queue_waits)) if queue_waits else None,
        "matched_intervals": len(intervals),
        "unmatched_starts": len(starts),
        "unmatched_ends": unmatched_ends,
        "malformed_events": malformed,
        "window_seconds": window,
    }
