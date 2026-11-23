#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a correction from the owner becomes a lesson, and an owner message that names a story is kept for it.

When the owner's prompt holds a correction phrase (the list is lib/lesson_flags.PHRASES), it records a flag in
~/.olivercode/lesson-flags/ and asks the session to run `olivercode lesson add`. Messages from other sessions
and system notifications are skipped. Each owner message that names a story (#N) is also appended to the decisions file for that story's builder (#884). The prompt is never blocked, and the hook fails open on its own error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import lesson_flags, owner_decisions  # noqa: E402
import hook_fires  # noqa: E402

CONTEXT = ("The owner corrected this session. Run `olivercode lesson add --what ... --why ... --rule ...` before you go on. "
           "See docs/RULES.md, Execution.")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    prompt = str(data.get("prompt") or "")
    if lesson_flags.from_owner(prompt):
        owner_decisions.record(prompt, str(data.get("session_id") or ""))
    if lesson_flags.record(str(data.get("prompt") or "")) is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": CONTEXT}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(hook_fires.run("lesson_capture", main))
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"lesson_capture failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
