"""What a session loads at start, in words, against the contextWords budget in docs/BUDGET.json.

The always-loaded files are ~/.claude/CLAUDE.md and VOICE.md (resolved through their links) and the
CLAUDE.md of the repo the session opens in. The harness fails over budget so it cannot grow the
context an agent starts with.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.local_config import OC_ROOT, claude_dir


def loaded_files(repo: Path | None = None) -> list[Path]:
    files = [claude_dir() / "CLAUDE.md", claude_dir() / "VOICE.md"]
    if repo and (repo / "CLAUDE.md").is_file():
        files.append(repo / "CLAUDE.md")
    seen, out = set(), []
    for f in files:
        if f.is_file() and f.resolve() not in seen:
            seen.add(f.resolve())
            out.append(f)
    return out


def budget() -> int | None:
    try:
        return int(json.loads((OC_ROOT / "docs" / "BUDGET.json").read_text(encoding="utf-8"))["contextWords"])
    except (OSError, ValueError, KeyError):
        return None


def measure(repo: Path | None = None) -> tuple[int, list[tuple[int, Path]]]:
    sizes = sorted(((len(f.read_text(encoding="utf-8", errors="ignore").split()), f) for f in loaded_files(repo)), reverse=True)
    return sum(n for n, _ in sizes), sizes


def report(repo: Path | None = None) -> tuple[bool, str]:
    """(within budget, the report text)."""
    total, sizes = measure(repo)
    limit = budget()
    lines = [f"{n:>6} words  {f}" for n, f in sizes]
    if limit is None:
        return True, f"A session loads {total} words (no contextWords budget set in docs/BUDGET.json).\n" + "\n".join(lines)
    if total > limit:
        return False, f"Over budget: a session loads {total} words against a budget of {limit}. Largest files:\n" + "\n".join(lines)
    return True, f"A session loads {total} words, within the budget of {limit}.\n" + "\n".join(lines)
