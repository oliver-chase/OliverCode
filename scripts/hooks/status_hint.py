#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a status question is answered from the status digest, with no tool call (#991).

When the owner's prompt asks what is building, what is left or when something finishes, the hook adds the board line and the open stories from
status-digest.md (cmd_status.digest_path) to the session, with the file's path and one line saying no tool call is needed. Every other prompt, and
every message from another session or a notification, gets nothing. The prompt is never blocked, and the hook fails open on its own error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import cmd_status, lesson_flags  # noqa: E402
import hook_fires  # noqa: E402

CHARS = 1200  # the board line and the open list, about three hundred tokens, is what a status answer needs
# A question about the board only: "status" alone, or "status" in a question or a status-of phrase. "the PR status is red" and "add a status field" are not questions.
STATUS_RE = re.compile(r"\bwhat(?:'s| is| are)\s+(?:the\s+)?status\b|\bstatus\s+(?:of|on)\b|^\s*(?:any\s+|the\s+)?status\s*\??\s*$"
                       r"|\bwhat(?:'s| is| are)\s+(?:still\s+)?(?:building|left|running|in progress|open)\b|\bhow far\b"
                       r"|\bwhen\s+(?:will|is|does)\s+(?:it|this|that|everything|the\s+\w+)\s+(?:finish|land|complete|be\s+done|be\s+ready|done|ready)\b",
                       re.IGNORECASE | re.MULTILINE)


def is_status_question(prompt: str) -> bool:
    return lesson_flags.from_owner(prompt) and bool(STATUS_RE.search(prompt))


def open_part(text: str) -> str:
    """The digest from its title through the open stories, before the landed section, at most CHARS characters."""
    head, _, _ = text.partition("\n## Landed")
    return head.strip()[:CHARS]


def context(prompt: str, path: Path | None = None) -> str:
    """The digest's board and open lines for a status question, or '' for any other prompt."""
    if not is_status_question(prompt):
        return ""
    path = path or cmd_status.digest_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Say so and offer to write it with `olivercode status digest`."
    return (f"Status from the status file {path}:\n{open_part(text)}\n"
            f"Answer from these lines with no tool call. The full status file is {path}, and the owner can read it there.")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    text = context(str(data.get("prompt") or ""))
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(hook_fires.run("status_hint", main))
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"status_hint failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
