#!/usr/bin/env python3
"""The per-user validation queue: at most N validations run at once on this Mac.

Many agents validating at the same moment drove the load past 60 on 8 cores, so every run
slowed and timed out. Each run takes a slot, one file per slot under ~/.olivercode/validate-slots
created with O_EXCL, and waits while every slot is held. A slot is reaped when its holder process is gone, when
its pid now belongs to a different process (the slot records the holder's start time), or when it is older than the
hard cap (HARD_CAP_SECONDS, well above one run), so a slow run under load keeps its slot while it lives. A run that
has waited WAIT_SECONDS goes ahead and says so on stderr, and any error in the queue itself lets the run go ahead, so
the queue never blocks validation. A damaged or old state file is repaired with a stderr line that names it.

    validate_queue.py acquire --pid PID [--label TEXT]   # blocks until a slot is free, prints its path
    validate_queue.py release SLOT_PATH
    validate_queue.py show                               # lists both queues
    validate_queue.py run [--render] COMMAND...          # holds a slot while COMMAND runs and returns its exit code

A second queue holds ffmpeg and render commands to one at a time under ~/.olivercode/render-slots, and `run --render` runs
the command under `nice -n 10`.

OLIVERCODE_VALIDATE_SLOTS sets N whatever the machine. Without it N is 1, or 2 on a machine with at least 12 cores whose last
ten validations kept load below its core count. Each validation appends its queue wait, run time and load average to
validate-runs.jsonl beside the slot folders. The render queue is one slot. OLIVERCODE_HOME moves the state folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HARD_CAP_SECONDS = 4 * 60 * 60  # a slot older than this is reaped even when its holder lives: no validation takes hours
WAIT_SECONDS = 10 * 60  # a blocked validation must report and proceed within ten minutes, not make the drain look hung for an hour
RENDER_NICE = "10"
CAPABLE_CORES = 12  # a machine with at least this many cores may run two validations when its recent load allows
RECENT_RUNS = 10  # how many logged validations the slot count looks at

# One row per queue: its folder, the variable that sets its slot count, that count by default, the variable a child sees
# while it holds a slot, and the name shown to the owner.
QUEUES = {
    "validate": {"folder": "validate-slots", "count_env": "OLIVERCODE_VALIDATE_SLOTS", "default": None,
                 "slot_env": "OLIVERCODE_VALIDATE_SLOT", "alias_env": "VALIDATE_QUEUE_SLOT", "title": "Validation"},
    "render": {"folder": "render-slots", "count_env": None, "default": 1,
               "slot_env": "OLIVERCODE_RENDER_SLOT", "title": "Render"},
}

# The variables a child sees while it holds a validation slot: repo scripts read the neutral name, so no repo names this tool.
SLOT_VARS = ("OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT")


def slots_dir(queue: str = "validate") -> Path:
    return Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / QUEUES[queue]["folder"]


_TOLD: set[str] = set()


def _note(message: str) -> None:
    """One stderr line per distinct message and process, so a repair is named once and never floods a poll loop."""
    if message not in _TOLD:
        _TOLD.add(message)
        print(message, file=sys.stderr)


def cores() -> int:
    return os.cpu_count() or 1


def runs_log() -> Path:
    return slots_dir().with_name("validate-runs.jsonl")


def log_run(wait: float, run_time: float) -> None:
    """Append one validation's queue wait, run time and the machine's load average to the run log. Never raises."""
    try:
        row = {"at": time.time(), "wait": round(wait, 1), "run": round(run_time, 1), "load": round(os.getloadavg()[0], 2)}
        with runs_log().open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except (OSError, AttributeError):
        pass


def recent_runs(n: int = RECENT_RUNS) -> list[dict]:
    try:
        lines = runs_log().read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def default_slots(queue: str = "validate") -> int:
    """The slot count with no override: one for render. For validation, two when the machine has at least 12 cores and the
    last ten validations each kept load below the core count, otherwise one (#776 timed 8 cores under load 44 to 104: a second run only adds load)."""
    fixed = QUEUES[queue]["default"]
    if fixed:
        return fixed
    if cores() < CAPABLE_CORES:
        return 1
    rows = recent_runs()
    ok = len(rows) >= RECENT_RUNS and all(isinstance(r.get("load"), (int, float)) and r["load"] < cores() for r in rows)
    return 2 if ok else 1


def slot_count(queue: str = "validate") -> int:
    q = QUEUES[queue]
    raw = os.environ.get(q["count_env"]) if q["count_env"] else None
    if raw is None or raw == "":
        return default_slots(queue)
    try:
        n = int(raw)
        if n < 1:
            raise ValueError
        return n
    except ValueError:
        _note(f"queue: {q['count_env']}={raw!r} is not a whole number of 1 or more, using {default_slots(queue)} (from {cores()} cores and recent load)")
        return default_slots(queue)


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def started_marker(pid: int) -> str | None:
    """The start time `ps` reports for pid, or None when it cannot be read. A recorded marker that no longer matches means
    the pid now belongs to another process, so a reused pid never keeps a dead holder's slot."""
    try:
        done = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return " ".join(done.stdout.split()) or None


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _holder_gone(data: dict) -> str | None:
    """Why the slot's holder no longer holds it, or None when it still does."""
    try:
        pid = int(data.get("pid", 0))
    except (TypeError, ValueError):
        return "its pid is not a number"
    if not _alive(pid):
        return f"holder pid {pid} is gone"
    recorded = data.get("pid_started")
    if recorded:
        now = started_marker(pid)
        if now and now != recorded:
            return f"pid {pid} now belongs to another process"
    return None


def reap(now: float | None = None, queue: str = "validate") -> list[str]:
    """Remove slots whose holder is dead, whose pid was reused, that are older than the hard cap or that are unreadable.
    Returns the reaped names, and names each repair on stderr."""
    now = time.time() if now is None else now
    reaped = []
    for path in sorted(slots_dir(queue).glob("slot-*.json")):
        data = _read(path)
        why = None
        if data is None:
            # A slot being written has no content for a moment, so only an old unreadable file is damaged.
            try:
                if now - path.stat().st_mtime > 60:
                    why = "it is unreadable (damaged or half written)"
            except OSError:
                continue
        else:
            why = _holder_gone(data)
            if why is None:
                try:
                    age = now - float(data.get("started", now))
                except (TypeError, ValueError):
                    age = 0.0
                    why = "its start time is not a number"
                if why is None and age > HARD_CAP_SECONDS:
                    why = f"it is {int(age / 60)} min old, past the {HARD_CAP_SECONDS // 60} min hard cap"
        if why:
            path.unlink(missing_ok=True)
            reaped.append(path.name)
            _note(f"queue: reclaimed {queue} slot {path.name} ({why})")
    return reaped


def _ensure_folder(folder: Path) -> None:
    """Create the slot folder. A plain file where the folder belongs (an old or damaged install) is moved aside and named."""
    if folder.exists() and not folder.is_dir():
        aside = folder.with_name(folder.name + ".damaged")
        folder.replace(aside)
        _note(f"queue: {folder} was a file, not a folder; moved it to {aside} and made a fresh slot folder")
    folder.mkdir(parents=True, exist_ok=True)


def try_acquire(pid: int, label: str = "", queue: str = "validate") -> Path | None:
    """Take a free slot for `pid`, or return None when every slot is held."""
    folder = slots_dir(queue)
    _ensure_folder(folder)
    reap(queue=queue)
    for i in range(1, slot_count(queue) + 1):
        path = folder / f"slot-{i}.json"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "started": time.time(), "label": label, "pid_started": started_marker(pid)}, f)
        return path
    return None


def acquire(pid: int, label: str = "", wait: float | None = None, poll: float = 2.0, say=print, queue: str = "validate") -> Path | None:
    """Block until a slot is free. Returns the slot, or None after `wait` seconds so the run goes ahead."""
    wait = WAIT_SECONDS if wait is None else wait
    deadline = time.time() + wait
    told = False
    while True:
        path = try_acquire(pid, label, queue)
        if path:
            return path
        if time.time() >= deadline:
            say(f"=== {queue}: waited {int(wait / 60)} min and every one of the {slot_count(queue)} slots is still held by a live run, "
                f"so this run goes ahead without a slot (`olivercode queue show` lists the holders) ===")
            return None
        if not told:
            kind = "render" if queue == "render" else "validation"
            say(f"=== {queue}: waiting for a {kind} slot ({slot_count(queue)} run at once; `olivercode queue show` lists them) ===")
            told = True
        time.sleep(poll)


def release(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


def _inside_slot(queue: str) -> bool:
    """True when this process already runs inside a held slot of the queue, so a nested run takes no second one and cannot deadlock."""
    names = SLOT_VARS if queue == "validate" else (QUEUES[queue]["slot_env"],)
    return any(os.environ.get(v, "").endswith(".json") for v in names)


def run(command: list[str], queue: str = "validate", poll: float = 2.0) -> int:
    """Run `command` holding a slot, with stdio inherited, and return its exit code. Any queue error runs it unqueued.
    A command already inside a held slot of the same queue runs in it. A render command runs under `nice -n 10`."""
    slot = None
    queued_at = time.time()
    try:
        if not _inside_slot(queue):
            slot = acquire(os.getpid(), Path.cwd().name, poll=poll, say=lambda m: print(m, file=sys.stderr), queue=queue)
    except Exception as exc:  # the queue fails open
        print(f"validate queue skipped: {exc}", file=sys.stderr)
    try:
        held = str(slot) if slot else "none"
        env = dict(os.environ) if _inside_slot(queue) else \
            {**os.environ, QUEUES[queue]["slot_env"]: held, **({q: held} if (q := QUEUES[queue].get("alias_env")) else {})}
        argv = ["nice", "-n", RENDER_NICE, *command] if queue == "render" else command
        started = time.time()
        try:
            code = subprocess.run(argv, env=env).returncode
        except FileNotFoundError:
            print(f"queue run: command not found: {command[0]}", file=sys.stderr)
            return 127
        if queue == "validate":
            log_run(started - queued_at, time.time() - started)
        return 128 - code if code < 0 else code
    finally:
        if slot:
            release(slot)


def show_queue(queue: str) -> str:
    reap(queue=queue)
    rows = []
    for path in sorted(slots_dir(queue).glob("slot-*.json")):
        data = _read(path) or {}
        try:
            age = int((time.time() - float(data.get("started", time.time()))) / 60)
        except (TypeError, ValueError):
            age = 0
        rows.append(f"  {path.stem}: pid {data.get('pid', '?')}, {age} min, {data.get('label') or 'no label'}")
    head = f"{QUEUES[queue]['title']} slots: {len(rows)} of {slot_count(queue)} held."
    return "\n".join([head, *rows])


def show() -> str:
    return "\n".join(show_queue(q) for q in QUEUES)


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["acquire"]:
            if _inside_slot("validate"):  # a run inside a held slot takes no second one
                print("none")
                return 0
            pid = int(argv[argv.index("--pid") + 1]) if "--pid" in argv else os.getppid()
            label = argv[argv.index("--label") + 1] if "--label" in argv else ""
            path = acquire(pid, label, say=lambda m: print(m, file=sys.stderr))
            print(path or "")
            return 0
        if argv[:1] == ["release"] and len(argv) == 2:
            if argv[1] != "none":
                release(Path(argv[1]))
            return 0
        if argv[:2] == ["run", "--render"] and len(argv) > 2:
            return run(argv[2:], "render")
        if argv[:1] == ["run"] and len(argv) > 1:
            return run(argv[1:])
        if argv == ["show"]:
            print(show())
            return 0
    except Exception as exc:  # the queue fails open: a run goes ahead without a slot
        print(f"validate queue skipped: {exc}", file=sys.stderr)
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
