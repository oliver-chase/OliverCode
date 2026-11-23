#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: each owner message that names a story (#N) is appended to the decisions ledger for that story's builder (#884, #1046).

It is the ledger's own writer, so the ledger keeps recording after the lesson_capture hook is removed (#983). It prints nothing to the session and never blocks the prompt, and it fails open on its own error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import lesson_flags, owner_decisions  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    prompt = str(data.get("prompt") or "")
    if lesson_flags.from_owner(prompt):
        owner_decisions.record(prompt, str(data.get("session_id") or ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"owner_decision_capture failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
