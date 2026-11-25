#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a status question is answered from the status digest, with no model turn (#991, #1000).

When the owner's prompt asks what is building, what is left or when something finishes, the hook reads the board line and the open stories from
status-digest.md (cmd_status.digest_path). A message that is only a status question is blocked, and those lines are the block reason, so no model
turn runs and the message never enters the thread. A mixed message goes through with the lines added as context. Every other prompt, a prompt that
starts with "ask:", and every message from another session or a notification, gets nothing. The hook fails open on its own error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import cmd_status, prompt_source  # noqa: E402

CHARS = 1200  # the board line and the open list, about three hundred tokens, is what a status answer needs
# A question about the board only: "status" alone, or "status" in a question or a status-of phrase. "the PR status is red" and "add a status field" are not questions.
STATUS_RE = re.compile(r"\bwhat(?:'s| is| are)\s+(?:the\s+)?status\b|\bstatus\s+(?:of|on)\b|^\s*(?:any\s+|the\s+)?status\s*\??\s*$"
                       r"|\bwhat(?:'s| is| are)\s+(?:still\s+)?(?:building|left|running|in progress|open)\b|\bhow far\b"
                       r"|\bwhen\s+(?:will|is|does)\s+(?:it|this|that|everything|the\s+\w+)\s+(?:finish|land|complete|be\s+done|be\s+ready|done|ready)\b",
                       re.IGNORECASE | re.MULTILINE)
ASK_RE = re.compile(r"\s*ask:", re.IGNORECASE)  # the owner's way to force a model turn on a status question
# Words that may remain once the status phrase is cut out: a message that leaves any other word, such as "and fix the parser", also asks for work.
FILLER = {"a", "about", "along", "and", "any", "are", "board", "done", "far", "finish", "how", "i", "is", "it", "left", "now", "of", "on", "please",
          "queue", "ready", "right", "so", "still", "status", "that", "the", "this", "thanks", "what", "when", "whats", "will", "you", "everything"}
WORD_RE = re.compile(r"[a-z']+")


def is_status_question(prompt: str) -> bool:
    return prompt_source.from_owner(prompt) and not ASK_RE.match(prompt) and bool(STATUS_RE.search(prompt))


def is_status_only(prompt: str) -> bool:
    """True when the prompt is a status question and nothing else: every word left after the status phrase is filler."""
    if not is_status_question(prompt):
        return False
    return all(word in FILLER for word in WORD_RE.findall(STATUS_RE.sub(" ", prompt).lower()))


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


def block_reason(path: Path) -> str:
    """The reason shown to the owner when a status-only prompt is blocked: the digest's lines, or a note that none is written yet."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Write it with `olivercode status digest`."
    return f"Status from the status file {path}:\n{open_part(text)}"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    prompt = str(data.get("prompt") or "")
    if is_status_only(prompt):
        # The block ends the turn, so the context beside it is never read; it keeps the #991 output shape for a status-only prompt.
        print(json.dumps({"decision": "block", "reason": block_reason(cmd_status.digest_path()),
                          "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context(prompt)}}))
        return 0
    text = context(prompt)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"status_hint failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
