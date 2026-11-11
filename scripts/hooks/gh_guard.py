#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `gh` command while the shared GitHub limit holds.

Any agent that hit the limit was recorded by gh_watch.py, so the others stop before they spend more of
the account's budget. `gh api rate_limit` is free and always allowed. Fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import gh_budget  # noqa: E402
import shlex  # noqa: E402


# OliverCode scripts that call gh themselves, which the hook cannot see inside.
GH_SCRIPTS = ("complete_story", "log_action", "check_board_hygiene", "check_qa_signoff", "check_kanban_baseline", "backlog-setup")


def uses_gh(command: str) -> bool:
    try:
        words = shlex.split(command, comments=False)
    except ValueError:
        return False
    if any(name in w for w in words for name in GH_SCRIPTS):
        return True
    for i, w in enumerate(words):
        if os.path.basename(w) == "gh" and (i == 0 or words[i - 1] in ("&&", "||", ";", "|", "(", "$(", "env", "time")):
            rest = words[i + 1:i + 3]
            return rest[:2] != ["api", "rate_limit"]
    return False


WRITE_WORDS = {("issue", "create"), ("issue", "close"), ("issue", "edit"), ("issue", "comment"), ("issue", "reopen"),
               ("pr", "create"), ("pr", "merge"), ("pr", "comment"), ("pr", "close"), ("pr", "edit"),
               ("project", "item-add"), ("project", "item-edit"), ("project", "item-create"), ("project", "item-delete"),
               ("project", "create"), ("project", "edit")}
WRITE_SCRIPTS = ("complete_story", "log_action", "backlog-setup")


def is_write(command: str) -> bool:
    """A command that changes GitHub: a gh write subcommand, a gh api call that is not a GET, or a script that writes."""
    try:
        words = shlex.split(command, comments=False)
    except ValueError:
        return False
    if any(name in w for w in words for name in WRITE_SCRIPTS):
        return True
    for i, w in enumerate(words):
        if os.path.basename(w) != "gh":
            continue
        rest = [x for x in words[i + 1:i + 6] if not x.startswith("-")]
        if tuple(rest[:2]) in WRITE_WORDS:
            return True
        if rest[:1] == ["api"] and any(x in words for x in ("-X", "--method", "-f", "-F", "--field", "--raw-field")) \
                and not any(m in words for m in ("GET",)):
            return True
    return False


def main() -> int:
    try:
        command = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
    except (json.JSONDecodeError, AttributeError):
        return 0
    if not uses_gh(command):
        return 0
    why = gh_budget.refusal() or (gh_budget.reserve_write() if is_write(command) else "")
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
