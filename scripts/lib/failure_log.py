"""The local failure log that the commit hooks write, and the gate-block report built on it.

One line per blocked commit or audit finding: time, repo, gate, reason, tab separated. The file sits in
~/.olivercode (OLIVERCODE_HOME overrides it), outside every repo, so no commit can carry it.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode")


def log_path() -> Path:
    return Path(os.environ.get("OLIVERCODE_FAILURE_LOG") or home() / "failures.log")


def record(gate: str, reason: str, repo: str = "") -> None:
    """Append one finding, the way the hooks do."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clean = " ".join(reason.split())[:200]
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{when}\t{repo or Path.cwd().name}\t{gate}\t{clean}\n")
    trim(path)


# A log keeps its newest lines, so it never grows past a fixed size however long the machine runs.
KEEP_LINES = 1000


def trim(path: Path, keep: int = KEEP_LINES) -> None:
    """Cut a log to its newest `keep` lines once it holds twice that, so most appends cost no rewrite."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return
    if len(lines) > 2 * keep:
        path.write_text("".join(lines[-keep:]), encoding="utf-8")


def entries() -> list[tuple[str, str, str, str]]:
    path = log_path()
    if not path.is_file():
        return []
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
    return [tuple(r) for r in rows if len(r) == 4]


def command_report(argv: list[str]) -> int:
    """`olivercode report [--days N]`: how many times each gate blocked in the last N days."""
    try:
        if argv and (argv[:1] != ["--days"] or len(argv) != 2):
            raise ValueError
        days = int(argv[1]) if argv else 7
    except ValueError:
        print("Usage: olivercode report [--days N]")
        return 1
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # maintain logs each unrepaired machine finding on every run, so it is a finding count and never a block.
    blocks = Counter(g for when, _r, g, _x in entries() if when >= f"{since:%Y-%m-%dT%H:%M:%SZ}" and g != "maintain")
    print(f"Harness report, last {days} days")
    print("Gate blocks:" + ("" if blocks else " none logged"))
    for gate, n in blocks.most_common():
        print(f"  {gate}: {n}")
    return 0
