#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook that no longer records anything (#1046).

The owner's messages that name a story are kept by owner_decision_capture.py, the decision ledger's only writer. This hook is left in place until #983 removes it. It prints nothing to the session and never blocks the prompt, and it fails open on its own error.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stdin.read()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"lesson_capture failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
