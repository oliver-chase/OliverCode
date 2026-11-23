"""One shared local copy of a GitHub Project board's item list, for every agent on this machine.

Reading the board costs GraphQL points from a budget every agent shares (`gh_budget.py`). This module keeps the
last item list in ~/.olivercode, so any number of agents read one file. When it is stale, one process refreshes it
under a file lock and the others wait for that refresh and then read it. A write to the board calls `invalidate`.
Standard library only.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

try:
    from lib import gh_budget
except ImportError:  # loaded bare, with scripts/lib on the path (batch_project.py and check_board_hygiene.py)
    import gh_budget

FRESH_SECONDS = 600


def _path(owner: str, number) -> Path:
    return gh_budget.home() / f"board-{owner}-{number}.json"


def _fresh(path: Path, clock) -> bool:
    try:
        return clock() - path.stat().st_mtime < FRESH_SECONDS
    except OSError:
        return False


def read(owner: str, number, fetch, use_cache: bool = True, clock=time.time) -> list:
    """The board's items: the shared copy when under ten minutes old, else one locked refresh through `fetch`."""
    path = _path(owner, number)
    if use_cache and _fresh(path, clock):
        return json.loads(path.read_text(encoding="utf-8"))
    gh_budget.home().mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # a second agent waits here, then reads what the first one fetched
        if use_cache and _fresh(path, clock):
            return json.loads(path.read_text(encoding="utf-8"))
        items = fetch()
        whole = path.with_suffix(".tmp")  # a lock-free reader must never see a half-written file, so swap it in whole
        whole.write_text(json.dumps(items), encoding="utf-8")
        os.replace(whole, path)
        return items


def invalidate() -> None:
    """Mark every cached board stale after a write."""
    for path in gh_budget.home().glob("board-*.json"):
        path.unlink(missing_ok=True)
