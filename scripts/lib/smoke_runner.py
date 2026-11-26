#!/usr/bin/env python3
"""The smoke tests of validate.sh: every tests/test_*.py module and every skills/*/scripts/test_*.py module, each in its own process (#757).

    smoke_runner.py [REPO_ROOT]

Each module runs as `python3 -m unittest -b MODULE` from its own folder, several at a time (OLIVERCODE_VALIDATE_JOBS, default the
machine's core count), largest file first so the slowest modules start first. -b buffers a module's output and this runner replays
it only for a failing module: several tests exercise paths that print "[FAIL]" or "Error:" by design, and unbuffered, a green run
read like a broken build. A module that would run longer than an even share of the work (by the seconds the last run recorded in
$OLIVERCODE_HOME/validate-timings.json, or its test count when none are recorded) is split into up to MAX_CHUNKS processes by test
id, so the longest module no longer sets the length of the gate. Exit 0 when every module passes, 1 otherwise. OLIVERCODE_VALIDATE_TIMES=1 also prints the ten slowest
modules, which is where to look when the smoke gate slows down.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


MAX_CHUNKS = 6
LISTER = ("import sys, unittest\n"
          "def walk(s):\n"
          "    for t in s:\n"
          "        yield from walk(t) if isinstance(t, unittest.TestSuite) else [t.id()]\n"
          "print('\\n'.join(walk(unittest.defaultTestLoader.loadTestsFromName(sys.argv[1]))))\n")


def timings_file() -> Path:
    return Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / "validate-timings.json"


def load_timings() -> dict[str, float]:
    """Seconds per module from the last run. A missing file is a fresh install (no timings); a damaged one is ignored and named."""
    path = timings_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items() if float(v) >= 0}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, AttributeError):
        print(f"smoke: {path} is damaged, so this run splits modules by test count and rewrites it", file=sys.stderr)
        return {}


def save_timings(seconds: dict[str, float]) -> None:
    path = timings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # timings only tune the split, so a read-only home loses nothing


def test_count(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return 1
    return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"))


def test_ids(folder: Path, module: str) -> list[str]:
    done = subprocess.run([sys.executable, "-c", LISTER, module], cwd=folder, capture_output=True, text=True)
    return [line for line in done.stdout.split("\n") if line] if done.returncode == 0 else []


def plan(mods: list[tuple[str, Path, str]], timings: dict[str, float], workers: int) -> list[tuple[str, str, Path, list[str]]]:
    """Work units (log name, module, folder, test ids to run or [] for the whole module), heaviest first."""
    counts = {name: test_count(folder / f"{module}.py") for name, folder, module in mods}
    known = [(timings[n], counts[n]) for n, _, _ in mods if n in timings and counts[n]]
    per_test = (sum(t for t, _ in known) / max(1, sum(c for _, c in known))) if known else 1.0
    weight = {n: timings.get(n, counts[n] * per_test) for n, _, _ in mods}
    share = sum(weight.values()) / max(1, workers)
    units = []
    for name, folder, module in mods:
        chunks = min(MAX_CHUNKS, counts[name], -int(-weight[name] // share)) if share > 0 and weight[name] > share else 1
        ids = test_ids(folder, module) if chunks > 1 else []
        if len(ids) < 2:
            units.append((weight[name], name, module, folder, []))
            continue
        chunks = min(chunks, len(ids))
        for k in range(chunks):
            units.append((weight[name] / chunks, f"{name}#{k + 1}", module, folder, ids[k::chunks]))
    return [u[1:] for u in sorted(units, key=lambda u: -u[0])]


def jobs() -> int:
    try:
        n = int(os.environ.get("OLIVERCODE_VALIDATE_JOBS", ""))
        if n >= 1:
            return min(4, n)
    except ValueError:
        pass
    return min(4, os.cpu_count() or 4)


def modules(root: Path) -> list[tuple[str, Path, str]]:
    """(name, folder, module) for every test module, largest source first."""
    found = [(p.stem, p.parent, p.stem) for p in sorted((root / "tests").glob("test_*.py"))]
    found += [(f"{p.parent.parent.name}-{p.stem}", p.parent, p.stem) for p in sorted(root.glob("skills/*/scripts/test_*.py"))]
    return sorted(found, key=lambda m: -(m[1] / f"{m[2]}.py").stat().st_size)


def run(root: Path, out=sys.stdout) -> int:
    mods = modules(root)
    if not mods:
        print("  Ran 0 tests across 0 modules, all passed", file=out)
        return 0
    with tempfile.TemporaryDirectory(prefix="olivercode-smoke-") as tmp:
        log_dir = Path(tmp)
        units = plan(mods, load_timings(), jobs())
        output_lock = threading.Lock()

        verbose = os.environ.get("OLIVERCODE_VALIDATE_VERBOSE", "1") != "0"

        def progress(message: str) -> None:
            # Per-module output is opt-in; failures and the final summary are always shown.
            if verbose:
                with output_lock:
                    print(message, file=out, flush=True)

        print(f"  Running {len(units)} test unit(s) across {len(mods)} module(s), {jobs()} workers.", file=out, flush=True)

        def one(unit):
            name, module, folder, ids = unit
            began = time.monotonic()
            progress(f"  [RUN ] {name}")
            try:
                with open(log_dir / f"{name}.log", "w", encoding="utf-8") as log:
                    code = subprocess.run([sys.executable, "-m", "unittest", "-b", *(ids or [module])], cwd=folder, stdout=log,
                                          stderr=subprocess.STDOUT).returncode
            except OSError as exc:
                code = 1
                (log_dir / f"{name}.log").write_text(f"Could not start test module: {exc}\n", encoding="utf-8")
            took = time.monotonic() - began
            label = "FAIL" if code else " OK "
            progress(f"  [{label}] {name} ({took:.1f}s)")
            return name, code, took

        run_began = time.monotonic()
        with ThreadPoolExecutor(max_workers=jobs()) as pool:
            results = list(pool.map(one, units))
        if os.environ.get("OLIVERCODE_VALIDATE_TIMES") or time.monotonic() - run_began >= SHOW_SLOWEST_AFTER:  # a long run names its slowest modules without being asked (#1180)
            print("  slowest units: " + ", ".join(f"{n} {t:.0f}s" for n, _, t in sorted(results, key=lambda r: -r[2])[:10]), file=out)
        ran = 0
        for name, _, _ in results:
            m = re.search(r"^Ran (\d+) test", (log_dir / f"{name}.log").read_text(encoding="utf-8", errors="replace"), re.M)
            ran += int(m.group(1)) if m else 0
        failed = sorted(name for name, code, _ in results if code)
        if failed:
            for name in failed:
                print(f"--- {name} ---", file=out)
                print((log_dir / f"{name}.log").read_text(encoding="utf-8", errors="replace"), end="", file=out)
            print(f"  Ran {ran} tests across {len(mods)} modules, {len(failed)} failed: {', '.join(failed)}", file=out)
            print("=== validate: python smoke tests FAILED ===", file=out)
            return 1
        spent: dict[str, float] = {}
        for name, _, took in results:
            spent[name.split("#")[0]] = spent.get(name.split("#")[0], 0.0) + took
        save_timings(spent)
        print(f"  Ran {ran} tests across {len(mods)} modules, all passed", file=out)
    return 0


SHOW_SLOWEST_AFTER = 30  # seconds a run takes before it prints its ten slowest units unasked


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    return run(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
