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
