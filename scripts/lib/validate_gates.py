#!/usr/bin/env python3
"""Run validate.sh's independent gates together, report each as it starts and finishes, replay each one's output in order, and
hold the run to a time budget (#757, #776).

    validate_gates.py [--timeout SECONDS] [--max-gates N] NAME=COMMAND...

Each argument is a gate: a name, then `=`, then a shell command. Up to OLIVERCODE_VALIDATE_GATES gates run at once (default: the
core count), each writing to its own file, and the rest start as running gates finish. A line goes to stderr the moment a gate
starts and the moment it finishes, with its elapsed seconds, so a slow run shows its step at once. At the end the output is
replayed in the order the gates were given, so the log reads as if they had run one after another. The exit code is the first
failing gate's exit code (any failing gate fails the run), and 0 when every gate passes.

The budget is OLIVERCODE_VALIDATE_TIMEOUT seconds. Unset, it is BASE_BUDGET seconds scaled by how loaded the machine is (the
one-minute load average over the core count, at least 1 and at most MAX_SCALE). BASE_BUDGET comes from measured runs with headroom
(the measurements are on #776). A run past its budget stops every gate still running with its whole process group, and fails
with exit 124 and a line that names each such gate, its elapsed seconds and the load, so the builder reruns that one gate.
No GNU `timeout` is involved.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE_BUDGET = 5 * 60  # #776: full runs took 70-122s at load 44-104 on 8 cores and up to 250s before, so 5 min, up to twice that under load
MAX_SCALE = 2.0
TIMEOUT_EXIT = 124
PROGRESS = "=== validate: gate "  # every live progress line starts with this, so `olivercode land` can pass them through


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw)
        return value if value > 0 else default
    except ValueError:
        if raw:
            print(f"validate: {name}={raw!r} is not a positive number, using {default:g}", file=sys.stderr)
        return default


def _load() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


def default_timeout() -> float:
    explicit = _number("OLIVERCODE_VALIDATE_TIMEOUT", 0)
    if explicit:
        return explicit
    return BASE_BUDGET * min(MAX_SCALE, max(1.0, _load() / (os.cpu_count() or 1)))


def default_max_gates() -> int:
    """How many gates run at once: OLIVERCODE_VALIDATE_GATES, or the core count."""
    return max(1, int(_number("OLIVERCODE_VALIDATE_GATES", os.cpu_count() or 1)))


def _kill(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            continue


def _start(command: str, log: Path, env: dict) -> subprocess.Popen:
    fh = open(log, "w", encoding="utf-8")
    try:
        return subprocess.Popen(["bash", "-c", command], stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True)
    finally:
        fh.close()


def _say(err, line: str) -> None:
    print(line, file=err, flush=True)


def run_gates(gates: list[tuple[str, str]], timeout: float | None = None, out=sys.stdout,
              err=sys.stderr, max_gates: int | None = None) -> int:
    """Run (name, command) gates, at most max_gates at once, and replay them in order. Returns the run's exit code."""
    timeout = default_timeout() if timeout is None else timeout
    max_gates = max(1, default_max_gates() if max_gates is None else max_gates)
    env = {**os.environ}
    env.setdefault("VALIDATE_QUEUE_SLOT", "none")  # a gate is part of this run, so it takes no slot of its own
    codes: dict[str, int] = {}
    took: dict[str, float] = {}
    stalled: list[str] = []
    run_began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="olivercode-gates-") as tmp:
        logs = {name: Path(tmp) / f"{i}-{name}.log" for i, (name, _) in enumerate(gates)}
        commands = dict(gates)
        waiting, procs, started = [name for name, _ in gates], {}, {}
        deadline = time.monotonic() + timeout
        while (waiting or procs) and time.monotonic() < deadline:
            for name in [n for n, p in procs.items() if p.poll() is not None]:
                codes[name] = procs.pop(name).returncode
                took[name] = took.get(name, 0.0) + time.monotonic() - started[name]
                word = "passed" if codes[name] == 0 else f"failed (exit {codes[name]})"
                _say(err, f"{PROGRESS}'{name}' {word} in {took[name]:.0f}s ===")
            while waiting and len(procs) < max_gates:
                name = waiting.pop(0)
                procs[name], started[name] = _start(commands[name], logs[name], env), time.monotonic()
                _say(err, f"{PROGRESS}'{name}' started ({len(procs)} running, {len(waiting)} waiting) ===")
            if procs:
                time.sleep(0.1)
        now = time.monotonic()
        for proc in procs.values():
            _kill(proc)
        stalled = list(procs) + waiting
        load, cores = _load(), os.cpu_count() or 1
        for name in procs:
            took[name] = took.get(name, 0.0) + now - started[name]
            _say(err, f"{PROGRESS}'{name}' still running after {now - started[name]:.0f}s at the {timeout:.0f}s budget "
                      f"(OLIVERCODE_VALIDATE_TIMEOUT), load {load:.1f} on {cores} cores; stopped. "
                      f"Rerun it alone: bash scripts/validate.sh --gate {name} ===")
        if waiting:
            _say(err, f"=== validate: never started before the budget: {', '.join(waiting)} ===")
        for name, _ in gates:
            if logs[name].exists():  # a gate the budget never reached has no log
                out.write(logs[name].read_text(encoding="utf-8", errors="replace"))
            if name in stalled:
                print(f"=== validate: stalled gate '{name}': no result within the {timeout:.0f}s budget ===", file=out)
    print(f"validate: gates took {time.monotonic() - run_began:.0f}s in all, at most {max_gates} at once, load {_load():.1f} "
          f"on {os.cpu_count() or 1} cores. Gate seconds: "
          + ", ".join(f"{n} {took[n]:.0f}" for n, _ in gates if n in took), file=err)
    failing = [codes[n] for n, _ in gates if n in codes and codes[n] != 0]
    if stalled:
        return TIMEOUT_EXIT
    return failing[0] if failing else 0


def main(argv: list[str]) -> int:
    timeout = max_gates = None
    gates: list[tuple[str, str]] = []
    it = iter(argv)
    for arg in it:
        if arg == "--timeout":
            timeout = float(next(it))
        elif arg == "--max-gates":
            max_gates = int(next(it))
        elif "=" in arg:
            name, command = arg.split("=", 1)
            gates.append((name, command))
        else:
            print(__doc__.strip())
            return 2
    if not gates:
        print(__doc__.strip())
        return 2
    return run_gates(gates, timeout, max_gates=max_gates)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
