#!/usr/bin/env python3
"""Claude Code PostToolUse hook (Bash): records a GitHub rate limit seen in any command's output.

The record is what gh_guard.py reads, so one agent hitting the limit holds every other agent's gh calls.
Fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import gh_budget  # noqa: E402
from gh_guard import uses_gh  # noqa: E402
import hook_fires  # noqa: E402


# gh starts an error line with "gh: ", so a file that only quotes one mid-line is not an error.
GH_ERROR = re.compile(r"^gh: |HTTP (403|429)", re.M)


def saw_limit(command: str, output: str) -> bool:
    """A limit counts only when the command ran gh or the output carries a gh error, so printing the guard's own
    source or docs, which name the limit phrases, never starts a hold."""
    if "api rate_limit" in command or not gh_budget.is_limit(output):
        return False
    return bool(uses_gh(command) or GH_ERROR.search(output))


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        session, key = data.get("session_id") or "", data.get("tool_use_id") or ""
        response = data.get("tool_response") or ""
        output = "\n".join(str(v) for v in response.values()) if isinstance(response, dict) else str(response)
    except (json.JSONDecodeError, AttributeError):
        return 0
    if saw_limit(command, output):
        gh_budget.note_limit(who="gh_watch", resources=gh_budget.limit_resources(command, output))
    if key and uses_gh(command):
        gh_budget.note_after(key, session, command)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(hook_fires.run("gh_watch", main))
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
