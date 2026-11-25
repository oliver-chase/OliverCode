"""Reads the desktop app's session records and the transcripts under ~/.claude/projects, for the scheduled-task spend report (#782)."""

from __future__ import annotations

import calendar
import json
import time
from pathlib import Path

from lib import failure_log
from lib.local_config import claude_dir


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
    headless = False
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh):
                try:
                    row = json.loads(line)
                    headless = headless or row.get("entrypoint") == "sdk-cli"
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
    return (first[0], largest) if first and largest and not headless else None

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


def _local_day(stamp: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(stamp))


def _scan_chat(path: Path) -> dict:
    """What one transcript holds for the spend panel: whether it is a headless runner session, tokens read and calls per local day, and its first-call
    prompt size with that call's day. A prompt token is read on every call, so tokens read are input, cache-creation and cache-read tokens, each message
    id once at its largest usage (#1150)."""
    seen: dict[str, tuple[float, int]] = {}
    headless = False
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh):
                try:
                    row = json.loads(line)
                    headless = headless or row.get("entrypoint") == "sdk-cli"
                    message = row.get("message") or {}
                    usage = message.get("usage") or {}
                    if row.get("type") != "assistant" or not usage:
                        continue
                    stamp = calendar.timegm(time.strptime(str(row.get("timestamp"))[:19], "%Y-%m-%dT%H:%M:%S"))
                    total = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                except (ValueError, AttributeError, TypeError, OverflowError):
                    continue
                key = str(message.get("id") or f"line{n}")
                if total > 0 and total >= seen.get(key, (0, 0))[1]:
                    seen[key] = (min(stamp, seen[key][0]) if key in seen else stamp, total)
    except OSError:
        return {"headless": True, "days": {}, "start": None}
    days: dict[str, list[int]] = {}
    for stamp, total in seen.values():
        slot = days.setdefault(_local_day(stamp), [0, 0])
        slot[0] += total
        slot[1] += 1
    first = min(seen.values(), key=lambda v: v[0]) if seen else None
    return {"headless": headless, "days": days, "start": [_local_day(first[0]), first[1]] if first else None}


def chat_spend(projects: Path | None = None, days: int = 7, now: float | None = None, cache_path: Path | None = None) -> dict[str, dict]:
    """{local day: {"tokens", "calls", "starts": [first-call prompt sizes], "chats": [(file stem, tokens, calls)]}} for desktop chats in the last N days (#1150).
    A headless session is the runner's and is counted from the run log, so it is left out. Each transcript is read once and kept in a cache keyed by its
    size and modified time, so a page rewrite reads only the transcripts that changed."""
    projects = projects or claude_dir() / "projects"
    now = time.time() if now is None else now
    cutoff = now - max(1, days) * 86400
    cache_path = cache_path or failure_log.home() / "chat-usage-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    fresh, out = {}, {}
    wanted = {_local_day(now - back * 86400) for back in range(max(1, days))}
    for path in projects.glob("*/*.jsonl") if projects.is_dir() else []:
        try:
            info = path.stat()
        except OSError:
            continue
        if info.st_mtime < cutoff:
            continue
        sig = [info.st_size, info.st_mtime]
        scan = cache.get(str(path)) if (cache.get(str(path)) or {}).get("sig") == sig else {**_scan_chat(path), "sig": sig}
        fresh[str(path)] = scan
        if scan.get("headless"):
            continue
        for day, (tokens, calls) in scan["days"].items():
            if day in wanted:
                slot = out.setdefault(day, {"tokens": 0, "calls": 0, "starts": [], "chats": []})
                slot["tokens"] += tokens
                slot["calls"] += calls
                slot["chats"].append((path.stem, tokens, calls))
        if scan.get("start") and scan["start"][0] in wanted:
            out.setdefault(scan["start"][0], {"tokens": 0, "calls": 0, "starts": [], "chats": []})["starts"].append(scan["start"][1])
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(fresh), encoding="utf-8")
    except OSError:
        pass  # an unwritable home leaves the cache cold, so the next rewrite reads every transcript again
    return out
