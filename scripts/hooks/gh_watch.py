#!/usr/bin/env python3
"""Claude Code PostToolUse hook (Bash): records a GitHub rate limit seen in any command's output.

The record is what gh_guard.py reads, so one agent hitting the limit holds every other agent's gh calls.
Fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import gh_budget  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        output = json.dumps(data.get("tool_response") or "")
    except (json.JSONDecodeError, AttributeError):
        return 0
    if "api rate_limit" not in command and gh_budget.is_limit(output):
        gh_budget.note_limit(who="gh_watch")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
