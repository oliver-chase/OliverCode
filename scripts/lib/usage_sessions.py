"""Reads the desktop app's session records and the transcripts under ~/.claude/projects, for the scheduled-task spend report (#782)."""

from __future__ import annotations

import calendar
import json
import time
from pathlib import Path

from lib import schedules
from lib.local_config import claude_dir


def app_records(directory: Path | None = None) -> dict[str, dict]:
    directory = directory or schedules.sessions_dir()
    records = {}
    for f in directory.glob("*/*/local_*.json") if directory.is_dir() else []:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(s, dict) and s.get("sessionId"):
            records[str(s["sessionId"])] = s
    return records


def transcript(cli_id: str, projects: Path | None = None) -> Path | None:
    projects = projects or claude_dir() / "projects"
    for f in projects.glob(f"*/{cli_id}.jsonl") if cli_id and projects.is_dir() else []:
        return f
    return None



def transcript_start(path: Path) -> tuple[float, int] | None:
    """Return (first assistant-call timestamp, prompt tokens read) from a CLI transcript.

    Streaming transcript rows can repeat one assistant message. Count the first
    message once, using the largest usage value recorded for that message.
    """
    first: tuple[float, str] | None = None
    largest = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh):
                try:
                    row = json.loads(line)
                    message = row.get("message") or {}
                    if row.get("type") != "assistant" or not message.get("usage"):
                        continue
                    stamp_text = str(row.get("timestamp") or "")[:19]
                    stamp = calendar.timegm(time.strptime(stamp_text, "%Y-%m-%dT%H:%M:%S"))
                    usage = message["usage"]
                    total = sum(int(usage.get(k) or 0) for k in (
                        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"
                    ))
                    if total <= 0:
                        continue
                    message_id = str(message.get("id") or f"line{line_no}")
                except (ValueError, AttributeError, TypeError, OverflowError):
                    continue
                if first is None:
                    first = (stamp, message_id)
                elif message_id != first[1]:
                    break
                largest = max(largest, total)
    except OSError:
        return None
    return (first[0], largest) if first and largest else None

def recent_chat_starts(projects: Path | None = None, days: int = 7, now: float | None = None) -> list[tuple[Path, int]]:
    """Desktop transcript paths and their first-call prompt sizes within the last N days."""
    projects = projects or claude_dir() / "projects"
    now = time.time() if now is None else now
    cutoff = now - max(0, days) * 86400
    out = []
    for path in projects.glob("*/*.jsonl") if projects.is_dir() else []:
        measured = transcript_start(path)
        if measured and cutoff <= measured[0] <= now:
            out.append((path, measured[1]))
    return sorted(out, key=lambda item: item[1], reverse=True)

def period_usage(path: Path, since: float) -> tuple[int, int, int] | None:
    """(input, output, cache) tokens for calls at or after `since`, each message id once at its largest usage; None when no call carries usage (#782)."""
    seen: dict[str, tuple[int, int, int]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for n, line in enumerate(lines):
        try:
            row = json.loads(line)
            message = row.get("message") or {}
            usage = message.get("usage") or {}
            stamp = calendar.timegm(time.strptime(str(row.get("timestamp"))[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, AttributeError, TypeError, OverflowError):
            continue
        if usage and stamp >= since:
            get = lambda *keys: sum(int(usage.get(k) or 0) for k in keys if isinstance(usage.get(k), int))
            key = str(message.get("id") or f"line{n}")
            seen[key] = tuple(map(max, seen.get(key, (0, 0, 0)), (get("input_tokens"), get("output_tokens"), get("cache_creation_input_tokens", "cache_read_input_tokens"))))
    if not seen:
        return None
    return tuple(sum(v[i] for v in seen.values()) for i in range(3))  # type: ignore[return-value]
