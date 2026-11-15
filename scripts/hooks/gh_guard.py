#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `gh` command while the shared GitHub limit holds.

Any agent that hit the limit was recorded by gh_watch.py, so the others stop before they spend more of
the account's budget. `gh api rate_limit` is free and always allowed. Fails open on anything it cannot parse.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import gh_budget  # noqa: E402
import shlex  # noqa: E402


# OliverCode scripts that call gh themselves, which the hook cannot see inside.
GH_SCRIPTS = ("complete_story", "log_action", "check_board_hygiene", "check_qa_signoff", "check_kanban_baseline", "backlog-setup")
# batch_project owns a durable queue and deliberately accepts work during a hold; it checks the hold
# before its own network calls. The outer guard must not reject it before it can queue the request.
QUEUE_SCRIPTS = ("batch_project",)


LEADERS = ("env", "time", "timeout", "nice", "sudo", "command", "exec")


def segments(command: str) -> list[list[str]]:
    """The words of each command the shell would run, with leading wrappers, variable assignments and an
    interpreter removed, so the first word is the program or script that runs."""
    out = []
    for seg in re.split(r"&&|\|\||[;|\n`]|\$\(", command):
        try:
            words = shlex.split(seg, comments=False)
        except ValueError:
            continue
        while words and (os.path.basename(words[0]) in LEADERS or re.fullmatch(r"[A-Za-z_]\w*=.*", words[0])
                         or re.fullmatch(r"-\S+|\d+[smh]?", words[0])):
            words = words[1:]
        if words and os.path.basename(words[0]).startswith(("python", "bash", "sh", "zsh")):
            words = [w for w in words[1:] if not w.startswith("-")] or words
            # `bash -c "gh pr merge 1"`: the command string is a command line of its own.
            if len(words) == 1 and " " in words[0]:
                out.extend(segments(words[0]))
                continue
        if words:
            out.append(words)
    return out


def _launcher_backlog_setup(words: list[str]) -> bool:
    """`olivercode backlog-setup`, which calls gh from inside the launcher."""
    return os.path.basename(words[0]) == "olivercode" and words[1:2] == ["backlog-setup"]


def uses_gh(command: str) -> bool:
    """A command that runs gh or a script that calls gh. Naming one, as `sed` or `grep` on its file does, is not running it."""
    for words in segments(command):
        head = os.path.basename(words[0])
        if head == "gh":
            if words[1:3] != ["api", "rate_limit"]:
                return True
        elif (not head.startswith(QUEUE_SCRIPTS) and head.startswith(GH_SCRIPTS)) or _launcher_backlog_setup(words):
            return True
    return False


WRITE_WORDS = {("issue", "create"), ("issue", "close"), ("issue", "edit"), ("issue", "comment"), ("issue", "reopen"),
               ("pr", "create"), ("pr", "merge"), ("pr", "comment"), ("pr", "close"), ("pr", "edit"),
               ("project", "item-add"), ("project", "item-edit"), ("project", "item-create"), ("project", "item-delete"),
               ("project", "create"), ("project", "edit")}
WRITE_SCRIPTS = ("complete_story", "log_action", "backlog-setup")


# gh's global flags whose value is the next word, which would otherwise read as the subcommand.
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname"}


def is_write(command: str) -> bool:
    """A command that changes GitHub: a gh write subcommand, a gh api call that is not a GET, or a script that writes."""
    try:
        words = shlex.split(command, comments=False)
    except ValueError:
        return False
    # A command string handed to a shell is judged as the command line it is.
    for i, w in enumerate(words[:-1]):
        if os.path.basename(w).startswith(("bash", "sh", "zsh")) and words[i + 1].startswith("-") and "c" in words[i + 1] \
                and i + 2 < len(words) and is_write(words[i + 2]):
            return True
    if any(_launcher_backlog_setup(seg) for seg in segments(command)) and "--apply" in words:
        return True
    for seg in re.split(r"&&|\|\||[;|\n]", command):
        try:
            head = shlex.split(seg)
        except ValueError:
            continue
        if head and os.path.basename(head[0]).startswith(("python", "bash", "sh")):
            head = head[1:]
        if head and any(os.path.basename(head[0]).startswith(name) for name in WRITE_SCRIPTS):
            return True
    for i, w in enumerate(words):
        if os.path.basename(w) != "gh":
            continue
        rest, skip = [], False
        for x in words[i + 1:i + 8]:
            if skip:
                skip = False
            elif x in GH_VALUE_FLAGS:
                skip = True
            elif not x.startswith("-"):
                rest.append(x)
        if tuple(rest[:2]) in WRITE_WORDS:
            return True
        if rest[:1] == ["api"] and any(x in words for x in ("-X", "--method", "-f", "-F", "--field", "--raw-field")) \
                and not any(m in words for m in ("GET",)):
            return True
    return False


def per_field_edit(command: str) -> bool:
    """A direct `gh project item-edit`, which sets one field of one card and spends about five points each."""
    return bool(re.search(r"\bgh\s+project\s+item-edit\b", command))


def refusal(command: str) -> str:
    """Why a `gh` command is refused, or '' when it may run. A write that passes the other checks is counted."""
    if not uses_gh(command):
        return ""
    why = gh_budget.refusal() or gh_budget.points_refusal()
    if not why and per_field_edit(command):
        why = ("A per-field `gh project item-edit` spends about five points a card. Put every card and field in one "
               "input file and run skills/backlog/scripts/batch_project.py, which sets them in a few calls.")
    return why or gh_budget.reserve_call() or (gh_budget.reserve_write() if is_write(command) else "")


def main() -> int:
    try:
        command = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
    except (json.JSONDecodeError, AttributeError):
        return 0
    why = refusal(command)
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
