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
import hashlib
import json
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

try:
    from lib import failure_log
    from lib.failure_log import home
except ImportError:  # loaded bare, with scripts/lib on the path
    import failure_log
    from failure_log import home

HOLD_SECONDS = 1200


def _env_int(name: str, default: int) -> int:
    """A positive whole number from the environment, else the default, so a bad value never fails the import."""
    try:
        value = int(os.environ.get(name) or default)
    except ValueError:
        return default
    return value if value > 0 else default


# GitHub also throttles a steady burst of writes whatever the points left, so the machine as a whole gets a
# rolling cap on writes.
WRITES_PER_HOUR = _env_int("OLIVERCODE_GH_WRITES_PER_HOUR", 90)
# Every gh call, read or write, counts against a per-minute cap so parallel agents slow down together.
CALLS_PER_MINUTE = _env_int("OLIVERCODE_GH_CALLS_PER_MINUTE", 30)
# Stop before GitHub does: below this many GraphQL points every agent holds until the reset. 0 switches it off.
POINTS_FLOOR = 500  # OLIVERCODE_GH_POINTS_FLOOR overrides it, read on each call so a test or session can change it
POINTS_TTL = 60
LIMIT_TEXT = re.compile(r"rate limit (already )?exceeded|secondary rate limit|abuse detection|graphql_rate_limit", re.IGNORECASE)


def _state() -> dict:
    try:
        return json.loads((home() / "gh-limit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


RESOURCES = ("rest", "graphql")


def _until(resource: str, state: dict | None = None) -> float:
    """The epoch time one resource is held until, 0 when it is free. "" asks about both, and a record with no
    resource (written before the two were tracked apart) holds both."""
    state = _state() if state is None else state
    names = RESOURCES if resource in ("", None) else (resource,)
    times = [float(state.get(n, 0)) for n in names] + [float(state.get("until", 0))]
    until = max(times)
    return until if until > time.time() else 0.0


def blocked_until(resource: str = "") -> float:
    """The epoch time calls of one resource ("rest" or "graphql", or "" for either) are held until, 0 when free."""
    return _until(resource)


def _fetch_rates() -> dict:
    """The account's REST and GraphQL budgets from `gh api rate_limit`, which costs nothing."""
    out = subprocess.run(["gh", "api", "rate_limit", "--jq",
                          ".resources|[.core.remaining,.core.reset,.graphql.remaining,.graphql.reset]|@tsv"],
                         capture_output=True, text=True, timeout=5, check=True).stdout.split()
    return {"rest": {"remaining": int(out[0]), "reset": int(out[1])}, "graphql": {"remaining": int(out[2]), "reset": int(out[3])}}


def limit_resources(command: str, output: str) -> tuple[str, ...]:
    """Which resources a limit message holds. GraphQL text holds GraphQL only, a secondary or abuse limit holds both,
    and any other limit holds what the command spends: REST for a `gh api` call, GraphQL for the rest."""
    low = output.lower()
    if "secondary rate limit" in low or "abuse detection" in low:
        return RESOURCES
    if "graphql" in low:
        return ("graphql",)
    try:
        from gh_guard import spends_points
    except ImportError:  # loaded outside the hook, where the guard is not on the path
        return ("graphql",)
    return ("graphql",) if spends_points(command) else ("rest",)


def note_limit(seconds: int = HOLD_SECONDS, who: str = "", resources: tuple[str, ...] = RESOURCES, fetch=None) -> float:
    """Record that a limit was seen on the named resources. Each is held until the reset the account reports when it
    is out, else for `seconds`; a longer hold is never shortened. Returns the latest time held until."""
    now = time.time()
    state = _state()
    rates: dict = {}
    if os.environ.get("OLIVERCODE_GH_PROBE", "1") != "0":
        try:
            rates = (fetch or _fetch_rates)()
        except Exception:  # noqa: BLE001 -- fall back to the default hold
            rates = {}
    held = 0.0
    for name in resources:
        rate = rates.get(name) or {}
        reset = rate.get("reset", 0)
        until = reset if rate.get("remaining", 1) == 0 and reset > now else now + seconds
        state[name] = max(until, _until(name, state))
        held = max(held, state[name])
    state.pop("until", None)
    state.update({"seen": now, "by": who})
    home().mkdir(parents=True, exist_ok=True)
    with failure_log.locked(home() / "gh-limit.json"):
        # the file is read again under the lock, so a limit another agent noted meanwhile keeps its longer hold
        latest = _state()
        for name in RESOURCES:
            state[name] = max(float(state.get(name, 0)), float(latest.get(name, 0)))
        failure_log.write_private(home() / "gh-limit.json", json.dumps(state) + "\n")
    return held


def clear() -> None:
    (home() / "gh-limit.json").unlink(missing_ok=True)


def refusal(resource: str = "") -> str:
    """The text that stops a gh call, or '' when GitHub may be called. `resource` is what the call spends: "rest",
    "graphql", or "" to ask whether anything is held."""
    until = blocked_until(resource)
    if not until:
        return ""
    when = time.strftime("%H:%M", time.localtime(until))
    if resource == "graphql":
        return (f"GitHub's GraphQL rate limit is out until about {when}, and REST calls still run. Use `gh api`, or queue the call "
                "with `olivercode gh-limit queue -- gh ...`. See docs/RULES.md, Execution.")
    return (f"GitHub's rate limit was hit, and every agent on this machine shares the hold until about {when}. Queue board writes with "
            "`olivercode gh-limit queue -- gh ...`. See docs/RULES.md, Execution.")


QUEUE = "gh-queue.jsonl"
QUEUE_REPORT = "gh-queue-report.txt"
REPLAY_LOCK = "gh-replay.lock"
# A queued write that fails this many times leaves the queue for the owner queue (`olivercode owner`).
OWNER_AFTER = 3


def enqueue(argv: list[str], cwd: str = "") -> int:
    """Queue one gh command to run at the GraphQL reset. Returns the queue length."""
    if not argv or os.path.basename(argv[0]) != "gh":
        raise ValueError("only gh commands are queued")
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / QUEUE, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps({"id": uuid.uuid4().hex, "argv": argv, "cwd": cwd or os.getcwd(), "queued": time.time()}) + "\n")
        fh.seek(0)
        return len(fh.read().splitlines())


def _parse(text: str) -> list[dict]:
    """The queued rows in file order. A row written before ids existed takes the hash of its line as its id."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append({**row, "id": row.get("id") or hashlib.sha1(line.encode("utf-8")).hexdigest()})
    return rows


def _read() -> list[dict]:
    try:
        return _parse((home() / QUEUE).read_text(encoding="utf-8"))
    except OSError:
        return []


def _settle(row_id: str, attempts: int | None = None) -> None:
    """Under the queue's lock, drop the row with this id, or record its failed attempts when `attempts` is given. The file is read
    again here, so a command queued while the replay runs is kept."""
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / QUEUE, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            rows = _parse(fh.read())
            if attempts is None:
                rows = [r for r in rows if r["id"] != row_id]
            else:
                rows = [{**r, "attempts": attempts} if r["id"] == row_id else r for r in rows]
            fh.seek(0)
            fh.truncate()
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _to_owner(argv: list[str], err: str) -> bool:
    """Put a write that keeps failing in the owner queue with the command and its error. False when the owner queue refuses the
    text, which leaves the write queued."""
    try:
        from lib import cmd_owner
        cmd_owner.add("gh-replay", f"a queued GitHub write failed {OWNER_AFTER} times and was not sent: run it by hand or drop it",
                      command=" ".join(argv)[:200], error=err[:200] or "no output")
    except (ImportError, ValueError):  # ImportError: loaded bare, where the owner queue is not on the path
        return False
    return True


def _run_gh(argv: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd if os.path.isdir(cwd) else None, capture_output=True, text=True, timeout=120)


def replay(run=None) -> str:
    """Run the queued gh commands once GraphQL is free. A command that succeeds leaves the queue at once, so it is never sent
    twice. One that fails stays queued with the failure counted, and after OWNER_AFTER failures it moves to the owner queue. A rate
    limit stops the run and counts as no failure. A replay that starts while another runs is refused. Returns the report, also saved
    in ~/.olivercode/gh-queue-report.txt. While GraphQL is held nothing runs. An empty queue returns '' and makes no gh call."""
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / REPLAY_LOCK, "a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "Another replay is already running, and it sends each queued command once."
        try:
            return _replay(run)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _replay(run) -> str:
    rows = _read()
    if not rows:
        return ""
    if blocked_until("graphql"):
        when = time.strftime("%H:%M", time.localtime(blocked_until("graphql")))
        return f"{len(rows)} queued gh command(s) wait for the GraphQL reset at about {when}."
    run = run or _run_gh
    lines, sent, owned = [], 0, 0
    for row in rows:
        argv = row.get("argv", [])
        cmd = " ".join(argv)[:80]
        try:
            done = run(argv, row.get("cwd", ""))
            failed, err = done.returncode != 0, (done.stderr or done.stdout or "").strip()
        except Exception as exc:  # noqa: BLE001 -- a timeout or a missing gh is a failed write, so it stays queued
            failed, err = True, str(exc)
        if not failed:
            _settle(row["id"])
            sent += 1
            lines.append(f"wrote: {cmd}")
            continue
        if is_limit(err):
            note_limit(who="replay", resources=limit_resources(cmd, err))
            lines.append(f"held: {cmd} (GitHub's limit stopped the run, so nothing more was sent and this failure is not counted)")
            break
        attempts = row.get("attempts", 0) + 1
        if attempts >= OWNER_AFTER and _to_owner(argv, err):
            _settle(row["id"])
            owned += 1
            lines.append(f"owner: {cmd} (failed {attempts} times, so it is in the owner queue)")
        else:
            _settle(row["id"], attempts)
            lines.append(f"kept: {cmd} ({err.splitlines()[-1][:100] if err else 'failed'})")
    moved = f", {owned} moved to the owner queue" if owned else ""
    report = f"{sent} of {len(rows)} queued gh command(s) written{moved}.\n" + "\n".join(lines)
    failure_log.write_private(home() / QUEUE_REPORT, report + "\n")
    return report


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
    return (f"This machine has made {WRITES_PER_HOUR} GitHub writes in the last hour, the cap under GitHub's burst limit. "
            f"Write again after about {when}. See docs/RULES.md, Execution.")


def reserve_call(now: float | None = None) -> str:
    """Count one gh call of any kind against a per-minute cap shared by every agent, so a burst from several agents
    slows down before GitHub refuses it. Returns '' when the call may go ahead, or the text naming the wait."""
    now = now or time.time()
    free_at = _reserve("gh-calls.json", 60, CALLS_PER_MINUTE, now)
    if not free_at:
        return ""
    return (f"This machine has made {CALLS_PER_MINUTE} gh calls in the last minute, the cap under GitHub's limit. "
            f"Try again in {math.ceil(free_at - now)} seconds. See docs/RULES.md, Execution.")


def _fetch_points() -> dict:
    """GraphQL points left and their reset, plus the REST (core) requests left. Reading the rate limit costs nothing."""
    out = subprocess.run(["gh", "api", "rate_limit", "--jq",
                          "[.resources.graphql.remaining,.resources.graphql.reset,.resources.core.remaining]|@tsv"],
                         capture_output=True, text=True, timeout=5, check=True).stdout.split()
    return {"remaining": int(out[0]), "reset": int(out[1]), "rest": int(out[2])}


def points_reading(fetch=None, now: float | None = None) -> dict:
    """The GraphQL points and REST requests left, from the reading cached for a minute in ~/.olivercode/gh-points.json, or a
    fresh one saved over it. Every gh hook call reads this, so a minute holds one `gh api rate_limit` call however many calls
    run. A failed read is saved as an empty reading for the same minute, so calls do not retry it. Fails open."""
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
    return data


def points_refusal(fetch=None, now: float | None = None) -> str:
    """Stop gh calls while the account's GraphQL points are under the floor, before GitHub refuses them. It reads the cached
    points reading, so a hook that runs on every call usually reads one file. Fails open."""
    floor = int(os.environ.get("OLIVERCODE_GH_POINTS_FLOOR") or POINTS_FLOOR)
    if floor <= 0:
        return ""
    now = now or time.time()
    data = points_reading(fetch, now)
    if data.get("remaining", floor) < floor and data.get("reset", 0) > now:
        when = time.strftime("%H:%M", time.localtime(data["reset"]))
        return (f"GitHub has {data['remaining']} GraphQL points left, under the shared reserve of {floor}, so gh calls hold "
                f"until about {when}. Queue the pending work. See docs/RULES.md, Execution.")
    return ""


COST_LOG = "gh-cost.jsonl"
COST_KEEP = 86400
GRAPHQL_HOURLY = 5000


def _read_rows(now: float, window: int) -> list[dict]:
    rows = []
    try:
        for line in (home() / COST_LOG).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if now - row.get("t", 0) <= window:
                rows.append(row)
    except OSError:
        pass
    return rows


def note_before(key: str, fetch=None, now: float | None = None) -> None:
    """Remember the GraphQL points and REST requests left before a gh call, keyed by the tool call. The reading is the cached one
    from points_reading, so this adds no rate-limit call of its own. Fails open."""
    try:
        now = now or time.time()
        path = home() / "gh-pending.json"
        try:
            pending = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pending = {}
        pending = {k: v for k, v in pending.items() if now - v["t"] < 600}
        left = points_reading(fetch, now)
        if "remaining" not in left:  # the read failed, so there is nothing to measure this call against
            return
        pending[key] = {"t": now, "remaining": left["remaining"], "rest": left.get("rest")}
        home().mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pending), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- fail open
        pass


def note_after(key: str, session: str, command: str, fetch=None, now: float | None = None) -> None:
    """Log what a finished gh call spent: the drop in GraphQL points and in REST requests since note_before. The readings come
    from the one-minute cache, so a call that finishes within a minute of its start can show no spend, and the figures are
    approximate when other agents spend at the same moment. One line per call in ~/.olivercode/gh-cost.jsonl, kept for 24 hours."""
    try:
        now = now or time.time()
        path = home() / "gh-pending.json"
        pending = json.loads(path.read_text(encoding="utf-8"))
        before = pending.pop(key)
        path.write_text(json.dumps(pending), encoding="utf-8")
        left = points_reading(fetch, now)
        if "remaining" not in left:
            return
        points = max(0, before["remaining"] - left["remaining"])
        rest = max(0, before["rest"] - left["rest"]) if before.get("rest") is not None and left.get("rest") is not None else 0
        row = {"t": now, "session": session, "cmd": " ".join(command.split())[:60], "points": points, "rest": rest}
        log = home() / COST_LOG
        kept = _read_rows(now, COST_KEEP)
        try:
            total = len(log.read_text(encoding="utf-8").splitlines())
        except OSError:
            total = 0
        if total != len(kept):  # a line is older than 24 hours, so rewrite the file without it
            log.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 -- fail open
        pass


def share_refusal(session: str, now: float | None = None) -> str:
    """Hold a session that has spent more than its fair share of the hour's points while others are also active."""
    floor = int(os.environ.get("OLIVERCODE_GH_POINTS_FLOOR") or POINTS_FLOOR)
    if not session or floor <= 0:
        return ""
    rows = _read_rows(now or time.time(), 3600)
    sessions = {r["session"] for r in rows} | {session}
    if len(sessions) < 2:
        return ""
    share = (GRAPHQL_HOURLY - floor) // len(sessions)
    mine = sum(r["points"] for r in rows if r["session"] == session)
    if mine <= share:
        return ""
    return (f"This session has spent {mine} GraphQL points this hour, over its share of {share} among {len(sessions)} "
            "active sessions, so it holds. See docs/RULES.md, Execution.")


def is_limit(text: str) -> bool:
    return bool(LIMIT_TEXT.search(text or ""))
