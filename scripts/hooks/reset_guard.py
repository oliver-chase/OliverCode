#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses `git reset --hard` where it could erase another session's work.

A main checkout is shared by every session, and a tree with uncommitted changes holds work that a hard reset destroys with no way back.
A clean linked worktree holds nothing to lose, so the reset is allowed there. Fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import commit_guard  # noqa: E402

RULES_DOC = "See docs/RULES.md, Execution."


def _git(where: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, timeout=10)


def reason(command: str, cwd: Path) -> str:
    """The refusal for a `git reset --hard` in a main checkout or a tree with uncommitted changes, or an empty string."""
    if "reset" not in command or "--hard" not in command:
        return ""
    for where, _keys, _env, args in commit_guard._commits(command, cwd, verbs=("reset",)):
        if "--hard" not in args:
            continue
        while not where.is_dir() and where != where.parent:
            where = where.parent
        top = _git(where, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or not top.stdout.strip():
            continue
        root = Path(top.stdout.strip())
        if (root / ".git").is_dir():
            return f"Refused: `git reset --hard` in {root.name}'s main checkout, shared by every session. Use `git merge --ff-only origin/main`. {RULES_DOC}"
        dirty = _git(where, "status", "--porcelain", "--untracked-files=no")
        if dirty.returncode == 0 and dirty.stdout.strip():
            return f"Refused: `git reset --hard` in {root.name} would erase uncommitted changes. Commit them or run `git checkout -- FILE`. {RULES_DOC}"
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
