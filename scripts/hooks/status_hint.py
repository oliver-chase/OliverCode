#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a status question is answered from the status digest, with no model turn (#991, #1000).

When the owner's prompt asks what is building, what is left or when something finishes, the hook reads the board line and the open stories from
status-digest.md (cmd_status.digest_path). A message that is only a status question is blocked, and those lines are the block reason, so no model
turn runs and the message never enters the thread. A mixed message goes through with the lines added as context. Every other prompt, a prompt that
starts with "ask:", and every message from another session or a notification, gets nothing. The hook fails open on its own error.

It also flags a long thread once (#1319): when an interactive session's transcript shows over 250,000 tokens of context, the first prompt after that
gets one line saying so and that "write a handoff" starts the move to a new thread. A marker in the OliverCode home keeps it to once per session, and a
headless builder is never flagged.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import failure_log  # noqa: E402
from lib import cmd_status  # noqa: E402

STALE_SECONDS = 3600  # a digest older than this is labeled with its age
LONG_TOKENS = 250_000  # a thread past this re-reads more cached context per turn than the turn's work costs (#1319)
TAIL_BYTES = 1_000_000  # the last model call's usage is near the end of the transcript
CHARS = 1200 # the board line and the open list, about three hundred tokens, is what a status answer needs
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


# A prompt that starts like this came from another session or the system, so the owner did not type it.
SKIP_PREFIXES = ("<cross-session-message", "[cross-session-message", "<system-notification", "[system-notification",
                 "system-notification:", "<system-reminder", "<task-notification", "<side-sessions-event", "<ci-monitor-event",
                 "[system notification", "another claude session sent a message", "<agent-message", "[subagent hand-back]",
                 "<scheduled-task", "background (from the session that started this one)")


def from_owner(prompt: str) -> bool:
    """True when the owner typed the prompt: it is not a message from another session, a notification or a hand-back."""
    text = (prompt or "").lstrip().lower()
    return bool(text) and not text.startswith(SKIP_PREFIXES) and "another claude session sent a message" not in text[:300]


def is_status_question(prompt: str) -> bool:
    return from_owner(prompt) and not ASK_RE.match(prompt) and bool(STATUS_RE.search(prompt))


def is_status_only(prompt: str) -> bool:
    """True when the prompt is a status question and nothing else: every word left after the status phrase is filler."""
    if not is_status_question(prompt):
        return False
    return all(word in FILLER for word in WORD_RE.findall(STATUS_RE.sub(" ", prompt).lower()))


def open_part(text: str) -> str:
    """The digest from its title through the open stories, before the landed section, at most CHARS characters."""
    head, _, _ = text.partition("\n## Landed")
    return head.strip()[:CHARS]


def age_note(path: Path, now: float | None = None) -> str:
    """'' for a digest written within the hour, else how old it is and that `olivercode status` gives the current figures (#1313)."""
    try:
        age = (now or time.time()) - path.stat().st_mtime
    except OSError:
        return ""
    if age <= STALE_SECONDS:
        return ""
    hours = int(age // 3600)
    old = f"{hours // 24} days" if hours >= 48 else f"{hours} hours"
    return f"This digest is {old} old. Run `olivercode status` for the current figures.\n"


def context(prompt: str, path: Path | None = None) -> str:
    """The digest's board and open lines for a status question, or '' for any other prompt."""
    if not is_status_question(prompt):
        return ""
    path = path or cmd_status.digest_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Say so and offer to write it with `olivercode status digest`."
    return (f"Status from the status file {path}:\n{age_note(path)}{open_part(text)}\n"
            f"Answer from these lines with no tool call. The full status file is {path}, and the owner can read it there.")


def context_tokens(transcript: Path) -> int:
    """The context size at the transcript's last model call: its input, cache-read and cache-write tokens, or 0 when none can be read (#1319)."""
    try:
        with transcript.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))  # shortcut: reads only the tail, so a final record over TAIL_BYTES reads as 0; upgrade if usage lines grow that large
            lines = handle.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        try:
            usage = json.loads(line).get("message", {}).get("usage")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(usage, dict):
            return sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def long_thread_note(data: dict) -> str:
    """One line, once per session, when an interactive thread's context passes LONG_TOKENS; '' for a short thread, a headless builder or a repeat."""
    session = re.sub(r"[^\w-]", "", str(data.get("session_id") or ""))
    transcript = str(data.get("transcript_path") or "")
    if not session or not transcript or os.environ.get("OLIVERCODE_HEADLESS") == "1":  # model.HEADLESS_ENV
        return ""
    if context_tokens(Path(transcript)) < LONG_TOKENS:
        return ""
    marker = failure_log.home() / f"long-thread-{session}"
    if marker.exists():
        return ""
    marker.touch()
    return ("This thread's context is past 250,000 tokens, so each turn costs more than the work in it. "
            "Tell the owner once, and that saying \"write a handoff\" starts the move to a new thread.")


def block_reason(path: Path) -> str:
    """The reason shown to the owner when a status-only prompt is blocked: the digest's lines, or a note that none is written yet."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Write it with `olivercode status digest`."
    return f"Status from the status file {path}:\n{age_note(path)}{open_part(text)}"


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
    text = "\n".join(part for part in (context(prompt), long_thread_note(data)) if part)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"status_hint failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
