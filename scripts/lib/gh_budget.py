"""One shared GitHub rate-limit budget for every agent on this machine.

GitHub's limit belongs to the account, so several agents calling `gh` at once drain it together and
all stop at once. This module keeps the state in ~/.olivercode (outside every repo):

- gh-limit.json records when a limit was seen and the time to hold off until
- a rolling cap on writes per hour, so a burst of board writes stops before GitHub throttles it

`scripts/hooks/gh_guard.py` refuses a `gh` command while the limit holds, and `gh_watch.py` records a
limit any agent hits, so one agent's failure protects all the others. Standard library only.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path

HOLD_SECONDS = 1200
# GitHub also throttles bursts of writes regardless of the points left (20 minutes of one write every 10
# seconds tripped it on 2026-11-11), so the machine as a whole gets a rolling cap on writes.
WRITES_PER_HOUR = int(os.environ.get("OLIVERCODE_GH_WRITES_PER_HOUR") or 90)
LIMIT_TEXT = re.compile(r"rate limit (already )?exceeded|secondary rate limit|abuse detection|graphql_rate_limit", re.IGNORECASE)


def home() -> Path:
    return Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode")


def _state() -> dict:
    try:
        return json.loads((home() / "gh-limit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def blocked_until() -> float:
    """The epoch time GitHub calls are held until, or 0 when nothing is held."""
    until = float(_state().get("until", 0))
    return until if until > time.time() else 0.0


def note_limit(seconds: int = HOLD_SECONDS, who: str = "") -> float:
    """Record that a limit was seen. Returns the time calls are held until; a longer hold is never shortened."""
    until = max(time.time() + seconds, blocked_until())
    home().mkdir(parents=True, exist_ok=True)
    (home() / "gh-limit.json").write_text(json.dumps({"until": until, "seen": time.time(), "by": who}) + "\n", encoding="utf-8")
    return until


def clear() -> None:
    (home() / "gh-limit.json").unlink(missing_ok=True)


def refusal() -> str:
    """The text that stops a gh call, or '' when GitHub may be called."""
    until = blocked_until()
    if not until:
        return ""
    when = time.strftime("%H:%M", time.localtime(until))
    return (f"GitHub's rate limit was hit and is shared by every agent on this machine. Hold all gh calls until about {when}. "
            "Queue the pending board writes in your report and make no further gh calls; `olivercode gh-limit clear` lifts the hold early.")


def reserve_write(now: float | None = None) -> str:
    """Count one GitHub write against the rolling hourly cap shared by every agent. Returns '' when the write may
    go ahead (and records it), or the text that stops it, naming when the oldest write falls out of the hour."""
    now = now or time.time()
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / "gh-writes.json", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            try:
                stamps = [t for t in json.loads(fh.read() or "[]") if now - t < 3600]
            except ValueError:
                stamps = []
            if len(stamps) >= WRITES_PER_HOUR:
                when = time.strftime("%H:%M", time.localtime(stamps[0] + 3600))
                return (f"This machine has made {len(stamps)} GitHub writes in the last hour, the cap that keeps every agent under "
                        f"GitHub's burst limit. Queue the rest in your report and write again after about {when}.")
            stamps.append(now)
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(stamps))
            fh.flush()
            return ""
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def is_limit(text: str) -> bool:
    return bool(LIMIT_TEXT.search(text or ""))
