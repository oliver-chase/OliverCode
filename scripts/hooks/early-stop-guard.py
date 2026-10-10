#!/usr/bin/env python3
"""Claude Code Stop hook: catches a turn that promises work instead of doing it.

EARLY-STOP-1 in docs/DECISIONS.md. OliverCode's own implementation of the
verified-effect idea in the third-party fablize plugin's finish-the-work.sh --
written fresh against this repo's own conventions (stdlib Python, no bash/python
hybrid), not vendored. Deterministic regex, not a model call: it looks at only
the closing paragraph of the last assistant turn for future-intent language
("I'll implement X", "let me build Y") with no tool call and no question to the
user, and asks the session to continue instead of stopping.

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
    r"say (go|yes|the word)|tell me|your call|if you want|once you confirm|waiting on you)",
    re.IGNORECASE,
)
TAIL_CHARS = 400


def _last_assistant_turn(transcript_path: Path) -> tuple[str, bool] | None:
    """Return (closing text, ended with a tool call) for the last assistant turn."""
    last_text = ""
    last_had_tool = False
    try:
        with transcript_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", obj)
                if obj.get("type") != "assistant" and msg.get("role") != "assistant":
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                tools = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if texts or tools:
                    last_text = "\n".join(texts).strip()
                    last_had_tool = bool(tools)
    except OSError:
        return None
    return last_text, last_had_tool


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
    last_text, last_had_tool = turn

    # Ended with a tool call (still working) or produced no text -> not an early stop.
    if last_had_tool or not last_text:
        print(json.dumps({}))
        return 0

    tail = last_text[-TAIL_CHARS:]
    promise = PROMISE_RE.search(tail)
    asks_user = ASKS_USER_RE.search(tail)

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
