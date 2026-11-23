"""The run lock: one run per repo at a time, whichever thread or terminal starts it (#992).

`olivercode drain REPO` and `olivercode dispatch N` take the lock before they build. A second one that finds the lock live starts no builder: it appends its
stories to the holder's queue and says who holds the run. The record sits in `runs/OWNER__REPO.json` in the OliverCode home and holds the process, who started
it, when, what it is building, the queued stories and the time of its last heartbeat. A holder whose process is gone, or whose heartbeat is older than
STALL_MINUTES, is dead, and the next run takes the lock over. Different repos have different locks, so runs in two repos go side by side. No model call.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from lib import gh_budget

STALL_MINUTES = 30  # a lock that has not reported for this long is dead (#987 reports the same limit as a stall)
BEAT_SECONDS = 60


def path(slug: str) -> Path:
    return gh_budget.home() / "runs" / (slug.replace("/", "__") + ".json")


@contextmanager
def _exclusive(slug: str):
    """Serialize every read-modify-write of one repo's record across processes."""
    target = path(slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.with_suffix(".lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read(target: Path) -> dict:
    try:
        rec = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def _write(target: Path, rec: dict) -> None:
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, target)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, OverflowError):
        return True
    return True


def dead_reason(rec: dict, now: float, alive=None) -> str:
    """Why the record's run is dead ('its process is gone', 'it has not reported for N minutes'), or '' while it is live."""
    if not rec:
        return "no run is recorded"
    if not (alive or pid_alive)(rec.get("pid", 0)):
        return f"its process {rec.get('pid')} is gone"
    quiet = now - float(rec.get("beat", 0))
    if quiet > STALL_MINUTES * 60:
        return f"it has not reported for {int(quiet // 60)} minutes"
    return ""


def active(slug: str, now: float | None = None, alive=None) -> dict:
    """The live run's record for a repo, or {} when none holds it. It reads and changes nothing."""
    rec = _read(path(slug))
    return {} if dead_reason(rec, now if now is not None else time.time(), alive) else rec


def building_elsewhere(slug: str, now: float | None = None, alive=None) -> int:
    """How many stories live runs in other repos are building, which count against the machine-wide builder limit (#1055)."""
    now = time.time() if now is None else now
    own = path(slug).name
    total = 0
    for record in path(slug).parent.glob("*.json"):
        rec = _read(record)
        if record.name != own and not dead_reason(rec, now, alive):
            total += len(rec.get("building") or [])
    return total


def acquire(slug: str, who: str, now: float, page: str = "", want: list[int] | None = None, pid: int | None = None, alive=None) -> tuple[dict, dict, str]:
    """Take the repo's lock. Returns (held, taken, why): `held` is the live holder's record when another run holds it, and then `want` is appended to its queue
    and nothing is taken. `taken` and `why` describe a dead holder this call replaced, else ({}, '')."""
    pid = pid or os.getpid()
    with _exclusive(slug) as target:
        rec = _read(target)
        why = dead_reason(rec, now, alive)
        if rec and not why and rec.get("pid") != pid:
            rec["queue"] = list(rec.get("queue") or []) + [n for n in (want or []) if n not in (rec.get("queue") or [])]
            _write(target, rec)
            return rec, {}, ""
        _write(target, {"pid": pid, "who": who, "since": now, "beat": now, "building": [], "queue": [], "page": page})
        return {}, (rec if rec else {}), (why if rec else "")


def beat(slug: str, pid: int, now: float, building: list[int] | None = None) -> None:
    """Report that the holder is alive, and what it is building when `building` is given. A record another run took over is left alone."""
    with _exclusive(slug) as target:
        rec = _read(target)
        if rec.get("pid") != pid:
            return
        rec["beat"] = now
        if building is not None:
            rec["building"] = sorted(building)
        _write(target, rec)


def take_queue(slug: str, pid: int) -> list[int]:
    """The stories other runs appended since the last call, which the holder works next. The queue empties."""
    with _exclusive(slug) as target:
        rec = _read(target)
        if rec.get("pid") != pid or not rec.get("queue"):
            return []
        queued, rec["queue"] = list(rec["queue"]), []
        _write(target, rec)
        return queued


def release(slug: str, pid: int) -> list[int]:
    """Drop the lock when this process holds it. Returns the stories appended after the last `take_queue`, which the caller works before it leaves."""
    with _exclusive(slug) as target:
        rec = _read(target)
        if rec.get("pid") != pid:
            return []
        queued = list(rec.get("queue") or [])
        if not queued:
            target.unlink(missing_ok=True)
        else:
            rec["queue"] = []
            _write(target, rec)
        return queued


def describe(rec: dict, now: float) -> str:
    """Who holds the run, since when, what it is building and where to watch it."""
    since = time.strftime("%H:%M", time.localtime(float(rec.get("since", now))))
    building = ", ".join(f"#{n}" for n in rec.get("building") or [])
    return (f"{rec.get('who', 'A run')} (process {rec.get('pid')}) holds the run since {since}, "
            f"{'building ' + building if building else 'building nothing yet'}." + (f" Status page: {rec['page']}" if rec.get("page") else ""))


class Heartbeat:
    """A background thread that reports every BEAT_SECONDS while a run builds, since a single builder can run past the stall limit."""

    def __init__(self, slug: str, pid: int, every: float = BEAT_SECONDS, clock=time.time):
        self.slug, self.pid, self.every, self.clock = slug, pid, every, clock
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.wait(self.every):
            try:
                beat(self.slug, self.pid, self.clock())
            except OSError:
                pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=5)
