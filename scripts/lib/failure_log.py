"""The local failure log that the commit hooks write, and the learning proposals and gate-block report built on it.

One line per blocked commit or audit finding: time, repo, gate, reason, tab separated. The file sits in
~/.olivercode (OLIVERCODE_HOME overrides it), outside every repo, so no commit can carry it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

RECUR = 3


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


def entries() -> list[tuple[str, str, str, str]]:
    path = log_path()
    if not path.is_file():
        return []
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
    return [tuple(r) for r in rows if len(r) == 4]


def normalize(reason: str) -> str:
    """The reason without file names, so the same failure in different files counts together."""
    return re.sub(r"\S*[/.]\S*\w", "<file>", reason)


def key(gate: str, reason: str) -> str:
    return f"{gate} | {normalize(reason)}"


def _list(name: str) -> list[str]:
    path = home() / name
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def rejected() -> set[str]:
    return set(_list("rejected.txt"))


def reject(proposal_key: str) -> None:
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / "rejected.txt", "a", encoding="utf-8") as f:
        f.write(proposal_key + "\n")


def proposals() -> list[tuple[str, list[str]]]:
    """Each failure that has recurred three times and was not rejected, with its three newest log lines."""
    groups: dict[str, list[str]] = {}
    for when, repo, gate, reason in entries():
        groups.setdefault(key(gate, reason), []).append("\t".join((when, repo, gate, reason)))
    skip = rejected()
    return [(k, lines[-RECUR:]) for k, lines in groups.items() if len(lines) >= RECUR and k not in skip]


def command_learn(argv: list[str]) -> int:
    """`olivercode learn`: propose one check or memory entry for a failure that keeps recurring."""
    if argv[:1] == ["--reject"] and len(argv) == 2:
        reject(argv[1])
        print("Rejected. That proposal will not be offered again.")
        return 0
    if argv[:1] == ["--accept"]:
        return _accept(argv[1:])
    if argv:
        print("Usage: olivercode learn [--reject KEY | --accept KEY --comparison FILE]")
        return 1
    due = proposals()
    if not due:
        print("Nothing due")
        return 0
    k, lines = due[0]
    print(f"Proposal: add one check or memory entry for the failure `{k}`, which has recurred {RECUR} or more times.")
    print("Evidence:")
    for line in lines:
        print(f"  {line}")
    print(f"Accept with: olivercode learn --accept \"{k}\" --comparison <file from olivercode eval compare>")
    print(f"Reject with: olivercode learn --reject \"{k}\"")
    return 0


def _accept(argv: list[str]) -> int:
    """Accept a proposal only with a comparison whose pass rate did not fall."""
    if len(argv) != 3 or argv[1] != "--comparison":
        print("Stopped: accepting a rule needs the comparison. Run `olivercode eval compare BEFORE AFTER --out FILE` and pass `--comparison FILE`.")
        return 1
    comparison = Path(argv[2]).expanduser()
    if not comparison.is_file():
        print(f"Stopped: {comparison} does not exist. Run `olivercode eval compare` first.")
        return 1
    data = json.loads(comparison.read_text(encoding="utf-8"))
    if data.get("after", {}).get("pass_rate", 0) < data.get("before", {}).get("pass_rate", 1):
        print("Stopped: the pass rate fell after the change, so the rule is not accepted by default. "
              f"Failing tasks: {', '.join(data.get('regressed', [])) or 'none named'}.")
        return 1
    print(f"Accepted. Add the rule, then link {comparison} in the story.")
    return 0


def command_report(argv: list[str]) -> int:
    """`olivercode report [--days N]`: how many times each gate blocked in the last N days."""
    days = int(argv[1]) if argv[:1] == ["--days"] and len(argv) == 2 else 7
    since = datetime.now(timezone.utc) - timedelta(days=days)
    blocks = Counter(g for when, _r, g, _x in entries() if when >= f"{since:%Y-%m-%dT%H:%M:%SZ}")
    print(f"Harness report, last {days} days")
    print("Gate blocks:" + ("" if blocks else " none logged"))
    for gate, n in blocks.most_common():
        print(f"  {gate}: {n}")
    return 0
