#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a clone or worktree created outside its home.

Repos live under repoRoot and worktrees under repoRoot/_worktrees (scripts/lib/placement.py).
The hook reads every simple command in the line and refuses `git clone` and `git worktree add`
whose destination falls outside. Fails open on anything it cannot parse, because a guard that
blocks a legitimate command on its own bug costs more than the case it misses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import commit_guard  # noqa: E402
from lib import placement  # noqa: E402


def reason(command: str, cwd: Path) -> str:
    if "git" not in command or not ("clone" in command or "worktree" in command):
        return ""
    try:
        for words in commit_guard._segments(command):
            why = placement.violation(words, cwd)
            if why:
                return why
    except ValueError:
        return ""
    return ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        cwd = Path(data.get("cwd") or ".")
    except (json.JSONDecodeError, AttributeError):
        return 0
    why = reason(command, cwd)
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
