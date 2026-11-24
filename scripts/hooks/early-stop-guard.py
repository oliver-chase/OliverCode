#!/usr/bin/env python3
"""Claude Code Stop hook: catches a turn that promises work without doing it.

The hook is stdlib Python
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

PROMISE_RE = re.compile(
    r"\b(I'?ll|I will|let me|next,? I|now I'?ll)\b[^.]{0,60}"
    r"\b(now|next|then|implement|create|write|add|run|fix|save|build|start|proceed)\b",
    re.IGNORECASE,
)
ASKS_USER_RE = re.compile(
    r"(shall i|would you like|do you want|want me to|let me know|which option|"
    r"say (go|yes|the word)|tell me|your call|if you want|waiting on you|"
    r"(once|when|after|if) you (approve|confirm|say|decide|answer|choose|pick|reply)|"
    r"on your (go|yes|approval|answer))",
    re.IGNORECASE,
)
QUOTED_RE = re.compile(r"```.*?```|`[^`\n]*`|\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d|^>.*$", re.DOTALL | re.MULTILINE)
# A closing message that hands the owner a step ("you need to run", "please open") must follow a tool call that ran it
# and was refused (#550, #622).
OWNER_STEP_RE = re.compile(
    r"\b(you(?:'ll| will)? (?:need|have|must|should) to|please (?:run|open|click|install|add|set|paste|enter|log|sign|go|copy|restart|check|create)|"
    r"(?:run|paste|copy) (?:this|the following|these)|you (?:can|could) (?:run|open|click|install|paste))",
    re.IGNORECASE,
)
# Words in a tool result that show the call was refused or failed (#622). Text the agent wrote never counts.
REFUSAL_RE = re.compile(
    r"\b(error|errno|denied|refused|failed|failure|traceback|timed out|blocked|unauthorized|forbidden|"
    r"not found|permission|exit(?:ed)? (?:code|status)? ?[1-9]|exit code: ?[1-9])\b",
    re.IGNORECASE,
)
COMMAND_RE = re.compile(r"`([^`\n]{2,})`")
TAIL_CHARS = 400
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
# A promise that depends on a later event or condition leaves nothing undone in this turn.
CONDITIONAL_RE = re.compile(r"\b(if|when|whenever|unless|later)\b", re.IGNORECASE)
# A question can leave the turn through a tool call: the desktop app's next-step box
# (its `ask` field) or the question tool. The closing text then holds no question mark,
# so a turn that ended waiting on the owner read as an unkept promise.
ASK_TOOLS = ("AskUserQuestion",)
NEXT_STEP_TOOL_SUFFIX = "__wrap_up"


def _ask_text(block: dict) -> str | None:
    """The question a tool call puts to the owner, "" when it asks with no readable text, None when it asks nothing."""
    name, data = block.get("name", ""), block.get("input") or {}
    if name in ASK_TOOLS:
        qs = [q for q in data.get("questions") or [] if isinstance(q, dict)]
        return " ".join(f"{q.get('question', '')} " + " ".join(str(o.get("label", "")) for o in q.get("options") or [] if isinstance(o, dict)) for q in qs)
    if name.endswith(NEXT_STEP_TOOL_SUFFIX) and data.get("ask"):
        return str(data["ask"])
    return None


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


def _current_turn(transcript_path: Path) -> list[dict] | None:
    """The transcript entries since the owner's last message, last first.

    Only the current turn matters, so the transcript is read from the end back to the owner's
    last message. Reading it from the start cost over a second on a long session."""
    turn: list[dict] = []
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
    return turn


def _last_assistant_turn(transcript_path: Path) -> tuple[str, bool, list[str]] | None:
    """Return (closing text, ended with a tool call, the questions put to the owner this turn)."""
    turn = _current_turn(transcript_path)
    if turn is None:
        return None
    last_text = ""
    last_had_tool = False
    asked: list[str] = []
    for obj in reversed(turn):
        msg = obj.get("message", obj)
        if obj.get("type") != "assistant" and msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        tools = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        asked += [t for t in (_ask_text(b) for b in tools) if t is not None]
        if texts or tools:
            last_text = "\n".join(texts).strip()
            last_had_tool = bool(tools)
    return last_text, last_had_tool, asked


def _closing_sentence(tail: str) -> str:
    """The last sentence or line of the tail. A promise earlier in the closing text, such as
    "I'll mention the hook now runs" before a finished summary, does not leave work undone."""
    parts = [p for p in SENTENCE_BREAK_RE.split(tail.strip()) if p.strip()]
    return parts[-1] if parts else ""


def _asks_owner(tail: str) -> bool:
    """Whether the message asks the owner something. A question mark counts when it ends the closing sentence; a mark inside
    quoted or code text, or in an earlier sentence, does not turn the check off."""
    spoken = re.sub(r"```.*?(?:```|$)", " ", tail, flags=re.DOTALL)
    spoken = QUOTED_RE.sub(" ", spoken)
    closing = _closing_sentence(spoken).rstrip(" \t)\"'\u201d*_")
    return closing.endswith("?") or bool(ASKS_USER_RE.search(spoken))


def _is_safe_path(path_str: str) -> bool:
    """Reject a transcript path outside TMPDIR/HOME -- hook input is untrusted."""
    if not path_str:
        return False
    allowed_roots = [Path(os.environ.get("TMPDIR", "/tmp")), Path.home()]
    try:
        resolved = Path(path_str).resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root.resolve()) for root in allowed_roots)


def _transcript_blocks(transcript_path: Path):
    """Every content block of the session's transcript, in order."""
    with transcript_path.open("rb") as f:
        for raw in f:
            try:
                msg = json.loads(raw)
                msg = msg.get("message", msg)
                blocks = msg.get("content")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                continue
            yield from ({**x, "_role": msg.get("role")} for x in blocks if isinstance(x, dict)) if isinstance(blocks, list) else ()


def _refused_calls(transcript_path: Path) -> list[str] | None:
    """The command or tool name of every tool call in the session whose result was an error or refusal."""
    calls: dict[str, str] = {}
    refused: list[str] = []
    try:
        for b in _transcript_blocks(transcript_path):
            if b.get("type") == "tool_use":
                calls[b.get("id", "")] = f"{b.get('name', '')} {(b.get('input') or {}).get('command', '')}"
            elif b.get("type") == "tool_result" and (b.get("is_error") or REFUSAL_RE.search(str(b.get("content", "")))):
                refused.append(calls.get(b.get("tool_use_id", ""), ""))
    except OSError:
        return None
    return refused


OWNER_LIST_FILE_RE = re.compile(r"(morning|owner|current_state|report|handoff)", re.IGNORECASE)


def _written_owner_lists(transcript_path: Path) -> str:
    """Text this turn wrote with Write or Edit into a morning, owner-list, report or state file (#622)."""
    found: list[str] = []
    try:
        for b in _transcript_blocks(transcript_path):
            if b.get("type") == "text" and b.get("_role") == "user":
                found.clear()
            i = b.get("input") if b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit") else None
            if isinstance(i, dict) and OWNER_LIST_FILE_RE.search(str(i.get("file_path", ""))):
                found.append(str(i.get("content") or i.get("new_string") or ""))
    except OSError:
        return ""
    return "\n".join(found)


def _handoff_without_attempt(text: str, transcript_path: Path) -> bool:
    """True when `text` hands the owner a step and no tool call in this session ran it and was refused.

    Refusal words in the text do not count: a step copied from an older list carries them with no attempt behind it (#622)."""
    if not OWNER_STEP_RE.search(text):
        return False
    refused = _refused_calls(transcript_path)
    if refused is None:
        return False
    commands = [c.strip() for c in COMMAND_RE.findall(text)]
    return not any(c in call for c in commands for call in refused) if commands else not refused


def _block_reason(input_data: dict) -> str:
    """Why this stop is sent back to work, or "" when it may stand."""
    # Loop guard: never block twice in a row on the same stop.
    if input_data.get("stop_hook_active") is True:
        return ""
    transcript_path = input_data.get("transcript_path", "")
    if not _is_safe_path(transcript_path):
        return ""
    turn = _last_assistant_turn(Path(transcript_path))
    if turn is None:
        return ""
    last_text, last_had_tool, asked_owner = turn
    # Ended with a tool call (still working) or produced no text -> not an early stop.
    if last_had_tool or not last_text:
        return ""
    tail = last_text[-TAIL_CHARS:]
    closing = _closing_sentence(tail)
    promise = PROMISE_RE.search(closing) and not CONDITIONAL_RE.search(closing)
    if asked_owner:
        return ""
    if _asks_owner(tail):
        return ""
    if promise:
        return PROMISE_REASON
    if _handoff_without_attempt(tail + "\n" + _written_owner_lists(Path(transcript_path)), Path(transcript_path)):
        return HANDOFF_REASON
    return ""


PROMISE_REASON = (
    "The previous response ended by stating an intent to do work without "
    "actually doing it. Do that work now with tool calls. End the turn only "
    "when the task is complete or you are blocked on input only the user can "
    "provide."
)
HANDOFF_REASON = (
    "The previous response hands the owner a step that no tool call in this session ran and saw refused. Run the "
    "step yourself first, even when an earlier list names it. If a tool refuses it, name the command and the error, "
    "then list the one step only the owner can take."
)


def main() -> int:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        input_data = {}
    reason = _block_reason(input_data)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- fail open, never block on the hook's own bug
        print(json.dumps({"systemMessage": f"early-stop-guard failed open: {exc}"}))
        raise SystemExit(0)
