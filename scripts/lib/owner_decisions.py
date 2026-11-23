"""The owner's own words about a story, kept for that story's builder (#884).

The owner_decision_capture hook appends each owner message that names a story (`#N`) to one file in the OliverCode home, one JSON line per
story the message names. The runner reads the entries for the story it briefs and no other. Standard library only.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

try:
    from lib.failure_log import home
except ImportError:  # loaded bare, with scripts/lib on the path
    from failure_log import home

FILE = "owner-decisions.jsonl"
_STORY = re.compile(r"(?<![\w&/])#(\d{1,6})\b")
MAX_CHARS = 4000  # the most of one message an entry keeps
MAX_ROWS = 1000  # the newest lines the file keeps; older decisions are dropped (#1046)
BRIEF_ENTRIES = 5  # the most owner messages one brief shows (#1046)
BRIEF_CHARS = 800  # the most characters one brief section holds, heading included (#1046)


def stories(prompt: str) -> list[int]:
    """The story numbers a prompt names, in the order it names them, once each."""
    return list(dict.fromkeys(int(n) for n in _STORY.findall(prompt or "")))


def record(prompt: str, session_id: str = "", now: float | None = None) -> int:
    """Append the prompt once for each story it names, then trim the file to MAX_ROWS. Returns how many entries were written. A file that cannot be written never stops a prompt."""
    numbers = stories(prompt)
    if not numbers:
        return 0
    when = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now if now is not None else time.time()))
    try:
        with open(home() / FILE, "a", encoding="utf-8") as fh:
            for n in numbers:
                fh.write(json.dumps({"story": n, "at": when, "session": session_id, "text": prompt.strip()[:MAX_CHARS]}) + "\n")
        _trim(home() / FILE)
    except OSError:
        return 0
    return len(numbers)


def _trim(path: Path) -> None:
    """Keep only the newest MAX_ROWS lines of the file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_ROWS:
        path.write_text("\n".join(lines[-MAX_ROWS:]) + "\n", encoding="utf-8")


def entries(n: int) -> list[dict]:
    """The recorded entries for story N, oldest first."""
    found = []
    try:
        lines = (home() / FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("story") == n and row.get("text"):
            found.append(row)
    return found


def brief_section(n: int) -> str:
    """The brief's section of the owner's newest messages about story N, at most BRIEF_ENTRIES of them within BRIEF_CHARS, or "" when there are none."""
    rows = entries(n)[-BRIEF_ENTRIES:]
    if not rows:
        return ""
    head = f"The owner's messages naming story #{n}, oldest first. They are decisions and stand unless the story says otherwise:\n\n"
    budget = BRIEF_CHARS - len(head) - 1
    kept: list[str] = []
    for r in reversed(rows):  # newest first, so the cut falls on the oldest
        block = f"{r.get('at', '')}:\n{r['text']}"
        sep = 2 if kept else 0
        if len(block) + sep > budget:
            if kept:
                break
            block = block[:budget]  # the newest message alone is cut to fit
        kept.insert(0, block)
        budget -= len(block) + sep
    return head + "\n\n".join(kept) + "\n"
