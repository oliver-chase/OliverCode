#!/usr/bin/env python3
"""Claude Code Stop hook: snapshots uncommitted work so a restart cannot lose it.

At the end of a turn it calls `olivercode wip save` for the session's repo and its worktrees, at
most once every 10 minutes per session (the last save time lives in ~/.olivercode/wip-last.json).
The snapshot is a ref under refs/wip/, so the working tree, the index and every branch stay as they
were. The whole call is held to 2 seconds, and it fails open with one stderr line on any error.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import failure_log  # noqa: E402
import wip  # noqa: E402

INTERVAL_S = 600
BUDGET_S = 2.0


def _due(session: str, now: float) -> bool:
    """True when this session has not saved in the last INTERVAL_S, and records this save."""
    path = failure_log.home() / "wip-last.json"
    try:
        marks = json.loads(path.read_text())
        marks = marks if isinstance(marks, dict) else {}
    except (OSError, ValueError):
        marks = {}
    if now - float(marks.get(session, 0) or 0) < INTERVAL_S:
        return False
    marks = {k: v for k, v in marks.items() if isinstance(v, (int, float)) and now - v < 7 * 86400}
    marks[session] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(marks))
    tmp.replace(path)
    return True


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    session = str(data.get("session_id") or "")
    cwd = Path(str(data.get("cwd") or os.getcwd()))
    if session and cwd.is_dir() and _due(session, time.time()):
        wip.save(cwd, session, budget=BUDGET_S, say=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken save must never stop a turn
        print(f"wip_save failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
