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
GH_SCRIPTS = ("complete_story", "log_action", "check_board_hygiene", "check_kanban_baseline", "backlog-setup")
# batch_project owns a durable queue and deliberately accepts work during a hold; it checks the hold
# before its own network calls. The outer guard must not reject it before it can queue the request.
QUEUE_SCRIPTS = ("batch_project",)


LEADERS = ("env", "time", "timeout", "nice", "sudo", "command", "exec")
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)


def strip_heredocs(command: str) -> str:
    """The command without heredoc bodies. A body is text for a program, such as a script a command writes or runs,
    and none of its lines is a command the shell runs, so a line that starts with `gh` there is not a gh call."""
    return HEREDOC.sub(lambda m: m.group(0)[:m.group(0).index("\n")], command)


def segments(command: str) -> list[list[str]]:
    """The words of each command the shell would run, with leading wrappers, variable assignments and an
    interpreter removed, so the first word is the program or script that runs."""
    out = []
    for seg in re.split(r"&&|\|\||[;|\n`]|\$\(", strip_heredocs(command)):
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


def _gh_use(words: list[str]) -> str:
    """What one command spends: "" when it makes no gh call, "rest" for `gh api` on a REST path, which costs the core
    budget and no GraphQL points, and "points" for any other gh call or a script that makes one."""
    head = os.path.basename(words[0])
    if head == "gh":
        if words[1:3] == ["api", "rate_limit"]:
            return ""
        return "rest" if words[1:2] == ["api"] and "graphql" not in words else "points"
    return "points" if (not head.startswith(QUEUE_SCRIPTS) and head.startswith(GH_SCRIPTS)) or _launcher_backlog_setup(words) else ""


def uses_gh(command: str) -> bool:
    """A command that runs gh or a script that calls gh. Naming one, as `sed` or `grep` on its file does, is not running it."""
    return any(_gh_use(words) for words in segments(command))


def spends_points(command: str) -> bool:
    """A command that spends GraphQL points: a gh call that is not a REST `gh api`, or a script that calls gh."""
    return any(_gh_use(words) == "points" for words in segments(command))


WRITE_WORDS = {("issue", "create"), ("issue", "close"), ("issue", "edit"), ("issue", "comment"), ("issue", "reopen"),
               ("pr", "create"), ("pr", "merge"), ("pr", "comment"), ("pr", "close"), ("pr", "edit"),
               ("project", "item-add"), ("project", "item-edit"), ("project", "item-create"), ("project", "item-delete"),
               ("project", "create"), ("project", "edit"),
               ("pr", "review"), ("pr", "ready"), ("pr", "reopen"), ("issue", "delete"), ("issue", "lock"), ("issue", "transfer"),
               ("release", "create"), ("release", "edit"), ("release", "delete"),
               ("repo", "create"), ("repo", "delete"), ("repo", "edit"), ("repo", "archive"), ("repo", "rename"),
               ("workflow", "run"), ("workflow", "enable"), ("workflow", "disable"), ("run", "rerun"), ("run", "cancel"),
               ("label", "create"), ("label", "edit"), ("label", "delete"), ("secret", "set"), ("secret", "delete"),
               ("variable", "set"), ("variable", "delete")}
WRITE_SCRIPTS = ("complete_story", "log_action", "backlog-setup")


# gh's global flags whose value is the next word, which would otherwise read as the subcommand.
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname"}


def is_write(command: str) -> bool:
    """A command that changes GitHub: a gh write subcommand, a gh api call that is not a GET, or a script that writes."""
    command = strip_heredocs(command)
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
    for head in segments(command):
        if any(os.path.basename(head[0]).startswith(name) for name in WRITE_SCRIPTS):
            return True
    for i, w in enumerate(words):
        if os.path.basename(re.split(r"[(`=]", w)[-1]) != "gh":  # a gh inside $(...), backticks or a subshell
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
        graphql_read = rest[1:2] == ["graphql"] and "mutation" not in command  # a query sends its text with -f too
        api_write_flags = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input")
        explicit = any(x in api_write_flags or x.startswith(("--method=", "--input=")) for x in words)
        if rest[:1] == ["api"] and explicit and not any(m in words for m in ("GET", "--method=GET")) and not graphql_read:
            return True
    return False


def per_field_edit(command: str) -> bool:
    """A direct `gh project item-edit`, which sets one field of one card and spends about five points each."""
    return bool(re.search(r"\bgh\s+project\s+item-edit\b", command))


def refusal(command: str, session: str = "") -> str:
    """Why a `gh` command is refused, or '' when it may run. A write that passes the other checks is counted."""
    if not uses_gh(command):
        return ""
    why = gh_budget.refusal("graphql" if spends_points(command) else "rest") or (spends_points(command) and (gh_budget.points_refusal() or gh_budget.share_refusal(session))) or ""
    if not why and per_field_edit(command):
        why = ("A per-field `gh project item-edit` spends about five points a card. Put every card and field in one input "
               "file for skills/backlog/scripts/batch_project.py. See docs/RULES.md, Execution.")
    return why or gh_budget.reserve_call() or (gh_budget.reserve_write() if is_write(command) else "")


def check(data: dict) -> str:
    """The refusal for one hook payload, or '' when the call may run. A gh call that may run is costed: the GraphQL points
    and REST requests left before it are noted, and gh_watch.py logs the drop afterwards."""
    command = (data.get("tool_input") or {}).get("command") or ""
    why = refusal(command, data.get("session_id") or "")
    if not why and data.get("tool_use_id") and uses_gh(command):
        gh_budget.note_before(data["tool_use_id"])
    return why


def top_level_steps(command: str) -> list[tuple[str, str]] | None:
    """The command as (step, separator) pairs split on `&&`, `;` and newlines outside quotes, or None when it holds
    anything the split cannot keep whole: a pipe, `||`, a substitution, a subshell, a group or a heredoc."""
    steps, buf, quote, i = [], "", "", 0
    while i < len(command):
        c = command[i]
        if quote:
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c in "|`(){<>" or command.startswith("$(", i):
            if c not in "<>" or command.startswith("<<", i):
                return None
        elif c in ";\n" or command.startswith("&&", i):
            sep = "&&" if c == "&" else c
            steps.append((buf, sep))
            buf, i = "", i + len(sep)
            continue
        buf += c
        i += 1
    return None if quote else steps + [(buf, "")]


def hold_only_gh(command: str, why: str) -> str | None:
    """A command with a git step and a gh step, rewritten so each gh step prints the refusal and fails while the git
    steps run as written. None when the command holds no git step or cannot be split safely."""
    steps = top_level_steps(command)
    if not steps or not any(os.path.basename(w[0]) == "git" for s, _ in steps for w in segments(s)):
        return None
    stub = f"{{ echo {shlex.quote(why)} >&2; false; }}"
    # A refused step must not stop the git steps after it, so `&&` after a stub becomes `;`.
    return "".join(f"{stub}{';' if sep == '&&' else sep}" if uses_gh(s) else f"{s}{sep}" for s, sep in steps)


def main() -> int:
    try:
        data = json.load(sys.stdin)
        why = check(data)
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"gh_guard: unreadable hook input, allowing: {type(exc).__name__}", file=sys.stderr)
        return 0
    if why:
        tool_input = data.get("tool_input") or {}
        mixed = hold_only_gh(tool_input.get("command") or "", why)
        if mixed:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                     "permissionDecisionReason": why,
                                                     "updatedInput": {**tool_input, "command": mixed}}}))
            return 0
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- fail open
        print(f"gh_guard failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
