#!/usr/bin/env python3
"""Claude Code Stop hook: catches a turn that promises work without doing it.

EARLY-STOP-1 in docs/DECISIONS.md has the reasoning. The hook is stdlib Python
and uses a deterministic regex with no model call: it looks at only
the closing sentence of the last assistant turn for future-intent language
("I'll implement X", "let me build Y") with no tool call and no question to the
user, and asks the session to continue.

Fails open on anything it cannot parse -- a hook that blocks a legitimate stop
because of its own bug is worse than a missed catch.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROMISE_RE = re.compile(
    r"\b(I'?ll|I will|let me|next,? I|now I'?ll)\b[^.]{0,60}"
    r"\b(now|next|then|implement|create|write|add|run|fix|save|build|start|proceed)\b",
    re.IGNORECASE,
)
ASKS_USER_RE = re.compile(
    r"(\?|shall i|would you like|do you want|want me to|let me know|which option|"
    r"say (go|yes|the word)|tell me|your call|if you want|waiting on you|"
    r"(once|when|after|if) you (approve|confirm|say|decide|answer|choose|pick|reply)|"
    r"on your (go|yes|approval|answer))",
    re.IGNORECASE,
)
TAIL_CHARS = 400
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# A question can leave the turn through a tool call: the desktop app's next-step box
# (its `ask` field) or the question tool. The closing text then holds no question mark,
# so a turn that ended waiting on the owner read as an unkept promise.
ASK_TOOLS = ("AskUserQuestion",)
NEXT_STEP_TOOL_SUFFIX = "__wrap_up"


def _asks_owner(block: dict) -> bool:
    name = block.get("name", "")
    if name in ASK_TOOLS:
        return True
    return name.endswith(NEXT_STEP_TOOL_SUFFIX) and bool((block.get("input") or {}).get("ask"))


def _is_owner_message(obj: dict, msg: dict) -> bool:
    """A user entry the owner wrote, which starts a new turn; a tool result does not."""
    if obj.get("type") != "user" and msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content)


def _reversed_lines(f, block: int = 1 << 16):
    """The file's lines, last first, read from the end in blocks."""
    f.seek(0, os.SEEK_END)
    pos, rest = f.tell(), b""
    while pos > 0:
        step = min(block, pos)
        pos -= step
        f.seek(pos)
        lines = (f.read(step) + rest).split(b"\n")
        rest = lines.pop(0)
        yield from reversed(lines)
    yield rest


def _last_assistant_turn(transcript_path: Path) -> tuple[str, bool, bool] | None:
    """Return (closing text, ended with a tool call, asked the owner this turn).

    Only the current turn matters, so the transcript is read from the end back to the owner's
    last message. Reading it from the start cost over a second on a long session."""
    turn = []
    try:
        with transcript_path.open("rb") as f:
            for raw in _reversed_lines(f):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                if _is_owner_message(obj, obj.get("message", obj)):
                    break
                turn.append(obj)
    except OSError:
        return None
    last_text = ""
    last_had_tool = False
    asked = False
    for obj in reversed(turn):
        msg = obj.get("message", obj)
        if obj.get("type") != "assistant" and msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        tools = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        asked = asked or any(_asks_owner(b) for b in tools)
        if texts or tools:
            last_text = "\n".join(texts).strip()
            last_had_tool = bool(tools)
    return last_text, last_had_tool, asked


def _closing_sentence(tail: str) -> str:
    """The last sentence or line of the tail. A promise earlier in the closing text, such as
    "I'll mention the hook now runs" before a finished summary, does not leave work undone."""
    parts = [p for p in SENTENCE_BREAK_RE.split(tail.strip()) if p.strip()]
    return parts[-1] if parts else ""


def _is_safe_path(path_str: str) -> bool:
    """Reject a transcript path outside TMPDIR/HOME -- hook input is untrusted."""
    if not path_str:
        return False
    allowed_roots = [Path(os.environ.get("TMPDIR", "/tmp")), Path.home()]
    try:
        resolved = Path(path_str).resolve()
    except OSError:
        return False
    return any(str(resolved).startswith(str(root.resolve())) for root in allowed_roots)


def main() -> int:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({}))
        return 0

    # Loop guard: never block twice in a row on the same stop.
    if input_data.get("stop_hook_active") is True:
        print(json.dumps({}))
        return 0

    transcript_path = input_data.get("transcript_path", "")
    if not _is_safe_path(transcript_path):
        print(json.dumps({}))
        return 0

    turn = _last_assistant_turn(Path(transcript_path))
    if turn is None:
        print(json.dumps({}))
        return 0
    last_text, last_had_tool, asked_owner = turn

    # Ended with a tool call (still working) or produced no text -> not an early stop.
    if last_had_tool or not last_text:
        print(json.dumps({}))
        return 0

    tail = last_text[-TAIL_CHARS:]
    promise = PROMISE_RE.search(_closing_sentence(tail))
    asks_user = asked_owner or ASKS_USER_RE.search(tail)

    if promise and not asks_user:
        print(json.dumps({
            "decision": "block",
            "reason": (
                "The previous response ended by stating an intent to do work without "
                "actually doing it. Do that work now with tool calls. End the turn only "
                "when the task is complete or you are blocked on input only the user can "
                "provide."
            ),
        }))
        return 0

    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- fail open, never block on the hook's own bug
        print(json.dumps({"systemMessage": f"early-stop-guard failed open: {exc}"}))
        raise SystemExit(0)
