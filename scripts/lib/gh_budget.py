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
import math
import os
import re
import subprocess
import time
from pathlib import Path

HOLD_SECONDS = 1200
# GitHub also throttles a steady burst of writes whatever the points left, so the machine as a whole gets a
# rolling cap on writes.
WRITES_PER_HOUR = int(os.environ.get("OLIVERCODE_GH_WRITES_PER_HOUR") or 90)
# Every gh call, read or write, counts against a per-minute cap so parallel agents slow down together.
CALLS_PER_MINUTE = int(os.environ.get("OLIVERCODE_GH_CALLS_PER_MINUTE") or 30)
# Stop before GitHub does: below this many GraphQL points every agent holds until the reset. 0 switches it off.
POINTS_FLOOR = 500  # OLIVERCODE_GH_POINTS_FLOOR overrides it, read on each call so a test or session can change it
POINTS_TTL = 60
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


def _reserve(name: str, window: int, cap: int, now: float) -> float:
    """Record one call in a rolling window shared by every agent. Returns 0 when it may go ahead, or the time the
    oldest call leaves the window when the cap is reached (and records nothing)."""
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / name, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            try:
                stamps = [t for t in json.loads(fh.read() or "[]") if now - t < window]
            except ValueError:
                stamps = []
            if len(stamps) >= cap:
                return stamps[0] + window
            stamps.append(now)
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(stamps))
            fh.flush()
            return 0.0
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def reserve_write(now: float | None = None) -> str:
    """Count one GitHub write against the rolling hourly cap shared by every agent. Returns '' when the write may
    go ahead (and records it), or the text that stops it, naming when the oldest write falls out of the hour."""
    free_at = _reserve("gh-writes.json", 3600, WRITES_PER_HOUR, now or time.time())
    if not free_at:
        return ""
    when = time.strftime("%H:%M", time.localtime(free_at))
    return (f"This machine has made {WRITES_PER_HOUR} GitHub writes in the last hour, the cap that keeps every agent under "
            f"GitHub's burst limit. Queue the rest in your report and write again after about {when}.")


def reserve_call(now: float | None = None) -> str:
    """Count one gh call of any kind against a per-minute cap shared by every agent, so a burst from several agents
    slows down before GitHub refuses it. Returns '' when the call may go ahead, or the text naming the wait."""
    now = now or time.time()
    free_at = _reserve("gh-calls.json", 60, CALLS_PER_MINUTE, now)
    if not free_at:
        return ""
    return (f"This machine has made {CALLS_PER_MINUTE} gh calls in the last minute, the cap that keeps every agent under "
            f"GitHub's limit. Try again in {math.ceil(free_at - now)} seconds.")


def _fetch_points() -> dict:
    out = subprocess.run(["gh", "api", "rate_limit", "--jq", ".resources.graphql|[.remaining,.reset]|@tsv"],
                         capture_output=True, text=True, timeout=5, check=True).stdout.split()
    return {"remaining": int(out[0]), "reset": int(out[1])}


def points_refusal(fetch=None, now: float | None = None) -> str:
    """Stop gh calls while the account's GraphQL points are under the floor, before GitHub refuses them. The reading
    is cached for a minute in ~/.olivercode so a hook that runs on every call usually reads one file. Fails open."""
    floor = int(os.environ.get("OLIVERCODE_GH_POINTS_FLOOR") or POINTS_FLOOR)
    if floor <= 0:
        return ""
    now = now or time.time()
    path = home() / "gh-points.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if now - data.get("at", 0) > POINTS_TTL:
        try:
            data = {"at": now, **(fetch or _fetch_points)()}
        except Exception:  # noqa: BLE001 -- fail open, and remember the failure for the same minute so every call does not retry it
            data = {"at": now}
        try:
            home().mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
    if data.get("remaining", floor) < floor and data.get("reset", 0) > now:
        when = time.strftime("%H:%M", time.localtime(data["reset"]))
        return (f"GitHub has {data['remaining']} GraphQL points left, under the shared reserve of {floor}, so every agent "
                f"on this machine holds gh calls until about {when}. Queue the pending work in your report.")
    return ""


def is_limit(text: str) -> bool:
    return bool(LIMIT_TEXT.search(text or ""))
