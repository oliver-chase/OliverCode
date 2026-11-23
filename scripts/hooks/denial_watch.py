#!/usr/bin/env python3
"""Claude Code PostToolUse hook (Bash): a command the permission classifier denied reaches the owner queue once (#781, #787).

The line carries the exact command to run, and `olivercode owner done ID` closes it when the owner has run it. Deterministic, with
no model call, and it fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import denials, hook_fires  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        response = data.get("tool_response") or ""
        output = "\n".join(str(v) for v in response.values()) if isinstance(response, dict) else str(response)
    except (json.JSONDecodeError, AttributeError):
        return 0
    item = denials.record(command, output, str(data.get("session_id") or ""), str(data.get("cwd") or ""))
    if item:
        text = (f"Queued owner step #{item['id']}: {item['step'][:100]}. Run `{item['command']}` yourself, then stop retrying it. "
                "See docs/RULES.md, Prepared owner steps.")
        print(json.dumps({"systemMessage": text, "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(hook_fires.run("denial_watch", main))
    except Exception:  # noqa: BLE001 -- a broken check must never stop a command
        raise SystemExit(0)
