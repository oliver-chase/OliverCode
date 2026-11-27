#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a clone or worktree created outside its home.

Repos live under repoRoot and worktrees under repoRoot/_worktrees (scripts/lib/placement.py).
The hook reads every simple command in the line and refuses `git clone` and `git worktree add`
whose destination falls outside. Fails open on anything it cannot parse, because a guard that
blocks a legitimate command on its own bug costs more than the case it misses.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from lib import placement, policy  # noqa: E402


def reason(command: str, cwd: Path) -> str:
    clone = "git" in command and ("clone" in command or "worktree" in command)
    create = "gh" in command and "create" in command
    if not (clone or create):
        return ""
    try:
        for words in policy.lex(command):
            why = (placement.violation(words, cwd) if clone else "") or (placement.repo_create_violation(words, cwd) if create else "")
            if why:
                return why
    except ValueError:
        return ""
    return ""
