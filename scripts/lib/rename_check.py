"""A rename story names its old name on a `Renames: OLD -> NEW` line, and closes only when OLD is gone (#838).

`refusal(body, root)` is what complete_story.py calls: it lists each tracked line of scripts, docs, tests, launchd
plists and the feature register that still holds OLD, except an alias line or a history file.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib import gitfiles

LINE = re.compile(r"^\s*Renames:\s*`?([^\s`]+)`?\s*(?:->|→)\s*`?([^\s`]+)`?\s*$", re.M)
SCANNED = ("scripts/", "docs/", "tests/")
ALIAS = re.compile(r"alias|formerly|renamed from|was renamed|previously named", re.I)
HISTORY = re.compile(r"history|changelog|LIMITS\.json|/audits?/", re.I)
SHOWN = 8


def parse(body: str | None) -> tuple[str, str] | None:
    """(old, new) from the story's `Renames:` line, or None."""
    m = LINE.search(body or "")
    return (m.group(1), m.group(2)) if m else None


def occurrences(root: Path, old: str) -> list[str]:
    """`path:line` for each tracked line that holds `old`, plus each tracked file name that does."""
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(old) + r"(?![A-Za-z0-9])")
    found = []
    for rel in gitfiles.tracked_files(root):
        if HISTORY.search("/" + rel) or not (rel.startswith(SCANNED) or rel.endswith(".plist")):
            continue
        if pattern.search(rel):
            found.append(f"{rel} (file name)")
        try:
            lines = (Path(root) / rel).read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue
        found += [f"{rel}:{n}" for n, line in enumerate(lines, 1) if pattern.search(line) and not ALIAS.search(line)]
    return found


def refusal(body: str | None, root: Path) -> str:
    """Why a rename story cannot close, or "" when it names no old name or the old name is gone."""
    names = parse(body)
    if not names:
        return ""
    old, new = names
    left = occurrences(Path(root), old)
    if not left:
        return ""
    shown = ", ".join(left[:SHOWN]) + (f" and {len(left) - SHOWN} more" if len(left) > SHOWN else "")
    return (f"the old name `{old}` still appears in {len(left)} place(s): {shown}. "
            f"Change each to `{new}`, or mark a deliberate one as an alias on its own line")
