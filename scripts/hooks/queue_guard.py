#!/usr/bin/env python3
"""PreToolUse guard: a validation command waits in the per-user queue in every repo, with no change to the repo.

`rewrite(command)` returns the command routed through `olivercode queue run --` (a render command through `queue run --render --`),
or None to leave it alone. It matches only a command in QUEUED_COMMANDS or RENDER_HEAD that starts the line, optionally after
`cd <dir> &&`, so `echo npm test`, `git commit -m "npm test"` and `ls && pytest` pass untouched. A command already inside the queue
(`queue run`, or OLIVERCODE_VALIDATE_SLOT, VALIDATE_QUEUE_SLOT or OLIVERCODE_RENDER_SLOT set) passes through.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import policy_parse  # noqa: E402

# The one list of validation commands that wait in the queue.
# The rewrite names the launcher by absolute path, because `olivercode` is on PATH only where the owner linked it.
LAUNCHER = f'python3 "{Path(__file__).resolve().parents[2] / "scripts" / "olivercode"}"'

QUEUED_COMMANDS = (
    "bash scripts/validate.sh",
    "bash scripts/land.sh",
    "./scripts/land.sh",
    "npm run validate",
    "npm run check",
    "npm test",
    "pytest",
    "python3 -m pytest",
    "python3 -m unittest",
)

# Render commands wait in the one-slot render queue and run under nice (#524): ffmpeg (ffprobe is cheap and stays out), any
# script named render*.py or *_render.py.
_PATH = r"(?:[^\s;&|<>()$`'\"]*/)?"
_PYTHON = rf"(?:{_PATH}python3?\s+)?"
RENDER_HEAD = (
    rf"(?:{_PATH}ffmpeg"
    rf"|{_PYTHON}{_PATH}[\w.-]*render[\w.-]*\.py)"
)

_CD = r"(?P<cd>cd\s+(?:\"[^\"]+\"|'[^']+'|[^\s;&|<>()$`]+)\s*&&\s*)?"
_ARGS = r"(?:[ \t]+[^;&|<>()$`\n]*)?"
_COMMAND = "|".join(re.escape(c) for c in sorted(QUEUED_COMMANDS, key=len, reverse=True))
_MATCH = re.compile(rf"^\s*{_CD}(?P<run>(?:{_COMMAND}){_ARGS})(?P<rest>.*)$", re.DOTALL)
_BOUNDARY = re.compile(rf"^\s*{_CD}(?:{_COMMAND})(?=\s|$|[;&|])")
_RENDER_MATCH = re.compile(rf"^\s*{_CD}(?P<run>{RENDER_HEAD}{_ARGS})(?P<rest>.*)$", re.DOTALL)
_RENDER_BOUNDARY = re.compile(rf"^\s*{_CD}{RENDER_HEAD}(?=\s|$|[;&|])")


def _wrap(command: str, boundary: re.Pattern, match: re.Pattern, flag: str) -> str | None:
    if not boundary.match(command):
        return None
    m = match.match(command)
    if not m:
        return None
    run = m.group("run").rstrip()
    trailing = m.group("run")[len(run):]
    return f"{m.group('cd') or ''}{LAUNCHER} queue run {flag}-- {run}{trailing}{m.group('rest')}".strip()


def _already_queued(command: str) -> bool:
    """True when a command of the line is `olivercode queue run`, alone or behind python3. The words "queue run" in a comment,
    an echo or a commit message are data. A line that does not parse is left alone."""
    try:
        for words in policy_parse.lex(command):
            words = policy_parse.unwrap(words)[1]
            for i, word in enumerate(words[:2]):
                if os.path.basename(word) == "olivercode" and words[i + 1:i + 3] == ["queue", "run"]:
                    return True
    except ValueError:
        return True
    return False


def rewrite(command: str) -> str | None:
    if "\n" in command.strip() or _already_queued(command):
        return None
    if not (os.environ.get("OLIVERCODE_VALIDATE_SLOT") or os.environ.get("VALIDATE_QUEUE_SLOT")):
        wrapped = _wrap(command, _BOUNDARY, _MATCH, "")
        if wrapped:
            return wrapped
    if not os.environ.get("OLIVERCODE_RENDER_SLOT"):
        return _wrap(command, _RENDER_BOUNDARY, _RENDER_MATCH, "--render ")
    return None
