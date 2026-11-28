"""What a session loads at start, in words, against the total the last passing run recorded.

The always-loaded files are ~/.claude/CLAUDE.md and VOICE.md (resolved through their links) and the
description line of every installed skill in
~/.claude/skills/*/SKILL.md, because the skill list reaches every session. The budget is a ratchet: the first run records
the total in ~/.olivercode/context-words.json (OLIVERCODE_HOME overrides the folder), a lower total lowers the record, and a
higher one fails. Growth stops and a trim never has to be forced. The owner raises the record by editing that file.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from lib import failure_log
from lib.local_config import claude_dir


def loaded_files() -> list[Path]:
    files = [claude_dir() / "CLAUDE.md", claude_dir() / "VOICE.md"]
    seen, out = set(), []
    for f in files:
        if f.is_file() and f.resolve() not in seen:
            seen.add(f.resolve())
            out.append(f)
    return out


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
DESCRIPTION = re.compile(r"^description:[ \t]*(.*(?:\n[ \t]+.*)*)", re.M)


def skill_description(path: Path) -> str:
    """The frontmatter description of a SKILL.md, or "" when it has none. Quotes and block markers are dropped."""
    head = FRONTMATTER.match(path.read_text(encoding="utf-8", errors="ignore"))
    found = DESCRIPTION.search(head.group(1)) if head else None
    if not found:
        return ""
    text = " ".join(found.group(1).split())
    return text[1:] if text[:1] in {">", "|"} and text[1:2] in {"", " "} else text


def skill_files() -> list[Path]:
    seen, out = set(), []
    for f in sorted((claude_dir() / "skills").glob("*/SKILL.md")):
        if f.is_file() and f.resolve() not in seen:
            seen.add(f.resolve())
            out.append(f)
    return out


def record_path() -> Path:
    return Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / "context-words.json"


def budget() -> int | None:
    """The recorded total, or None before the first run."""
    try:
        value = json.loads(record_path().read_text(encoding="utf-8")).get("words")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) and value > 0 else None


def _record(total: int) -> None:
    path = record_path()
    try:
        failure_log.write_private(path, json.dumps({"words": total}) + "\n")
    except OSError:
        pass


def measure() -> tuple[int, list[tuple[int, Path]]]:
    sizes = [(len(f.read_text(encoding="utf-8", errors="ignore").split()), f) for f in loaded_files()]
    sizes += [(len(skill_description(f).split()), f) for f in skill_files()]
    sizes.sort(key=lambda row: row[0], reverse=True)
    return sum(n for n, _ in sizes), sizes


def report() -> tuple[bool, str]:
    """(within budget, the report text). A first or lower total becomes the new record."""
    total, sizes = measure()
    limit = budget()
    lines = [f"{n:>6} words  {f}" for n, f in sizes[:8]]
    if limit is not None and total > limit:
        return False, (f"Over budget: a session loads {total} words, {total - limit} past the recorded {limit}. Largest files:\n"
                       + "\n".join(lines) + f"\nTrim the growth, or raise the record in {record_path()} with the reason on the story.")
    if limit is None or total < limit:
        _record(total)
    return True, f"A session loads {total} words, within the recorded {total if limit is None or total < limit else limit}.\n" + "\n".join(lines)


landed = budget  # the recorded total
