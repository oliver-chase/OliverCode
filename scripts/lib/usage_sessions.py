"""Finds the transcripts under ~/.claude/projects, for the scheduled-task spend report (#782), and sums one inside a time window for a chat landing (#1533) and a timed-out headless run (#1553)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lib.local_config import claude_dir


def transcript(cli_id: str, projects: Path | None = None) -> Path | None:
    projects = projects or claude_dir() / "projects"
    for f in projects.glob(f"*/{cli_id}.jsonl") if cli_id and projects.is_dir() else []:
        return f
    return None


TOKENS = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}


def usage_between(path: Path, start: float, end: float) -> dict:
    """The input, output, cache_read and cache_write tokens of the assistant messages in a transcript written from START to END (epoch seconds), each message id counted once,
    and the model of the last one ("" when none fell in the window)."""
    total, seen, model = dict.fromkeys(TOKENS, 0), set(), ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {**total, "model": model}
    for line in lines:
        try:
            row = json.loads(line)
            at = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()
            message = row["message"]
            usage = message["usage"]
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if row.get("type") != "assistant" or not start <= at <= end or (message.get("id") and message["id"] in seen):
            continue
        seen.add(message.get("id"))
        model = message.get("model") or model
        for key, field in TOKENS.items():
            total[key] += int(usage.get(field) or 0)
    return {**total, "model": model}


def runner(row: dict) -> str:
    """Who wrote a run-log row: "drain" when the row has no runner field."""
    return row.get("runner") or "drain"
