"""The size ceiling (#879, #882): `olivercode limits check` prints the tracked line count against the ceiling in docs/LIMITS.json and exits 0 always.

The ceiling is one number, the measured size the owner last accepted, and it warns and never blocks. Raising it is a hand edit of that number.
Tests, the ceiling file and the generated changelog are free. Standard library only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

LIMITS_FILE = "docs/LIMITS.json"


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def tracked_lines(root: Path, ref: str) -> dict[str, int]:
    """Path to line count of every text file at ref. Tests, the limits file and the generated changelog are free: they are the evidence or the daily output, not the weight."""
    counts: dict[str, int] = {}
    for row in git(root, "grep", "-I", "-c", "", ref).splitlines():
        path, _, n = row[len(ref) + 1:].rpartition(":")
        if n.isdigit() and not path.startswith("tests/") and path not in (LIMITS_FILE, "CHANGELOG.md"):
            counts[path] = int(n)
    return counts


def ceiling(root: Path) -> int | None:
    """The number in docs/LIMITS.json, or None when the file is missing or unreadable."""
    try:
        data = json.loads((root / LIMITS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data["limit"] if isinstance(data, dict) and isinstance(data.get("limit"), int) else None


def check(root: Path) -> list[str]:
    """The lines to print: the count against the ceiling, with a warning when it is over. Nothing here fails a commit or a land."""
    total, cap = sum(tracked_lines(root, "HEAD").values()), ceiling(root)
    if cap is None:
        return [f"The repo holds {total} tracked lines and {LIMITS_FILE} has no readable ceiling."]
    line = f"The repo holds {total} tracked lines against a ceiling of {cap}."
    if total > cap:
        line += f" It is {total - cap} over. This is a warning and blocks nothing: raise the number in {LIMITS_FILE} once the growth is accepted."
    return [line]
