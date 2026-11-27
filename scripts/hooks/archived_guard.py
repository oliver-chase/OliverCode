#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `git commit` or `git push` in a checkout GitHub has archived or deleted.

An archived repo accepts no push and a deleted one has no remote, so work committed there is stranded on this machine.
The hook reads every git command in the line, including `git -C <path>` and `cd X && git ...`, finds the checkout each
one runs in and asks scripts/lib/repo_state.py whether GitHub archived it. Fails open on anything it cannot parse or
look up, because a guard that blocks a legitimate command on its own bug costs more than the case it misses.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import commit_guard  # noqa: E402
import repo_gates  # noqa: E402
from lib import repo_state  # noqa: E402


def reason(command: str, cwd: Path, runner=None) -> str:
    if "git" not in command or not ("commit" in command or "push" in command):
        return ""
    for where, _keys, _env, _args in commit_guard._commits(command, cwd, verbs=("commit", "push")):
        root = repo_gates.repo_root(where)
        state = repo_state.archived(root, runner=runner) if root else None
        if state:
            return (f"Refused: {root.name} is {state} on GitHub, so its work cannot leave this machine. Do not commit, push or change "
                    "anything in this repo. See docs/RULES.md, Execution.")
    return ""
