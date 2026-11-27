#!/usr/bin/env python3
"""Claude Code PreToolUse hook helper (Bash, Monitor): refuses a watch that wakes a session on every event of a drain (#1490).

A Monitor, or a background Bash command, that follows the run log or runs plain `olivercode watch` spends tokens on every landing. A session waits with
`olivercode watch REPO --until-exit`, which prints once. A foreground command and a one-off read pass. It matches the command's text, so it narrows the
habit and does not seal it: a follower hidden in a script file passes. Fails open on anything it cannot parse.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import policy  # noqa: E402

RUN_LOG = "run-log"
LOOPS = {"while", "until", "for"}
KEYWORDS = LOOPS | {"do", "then", "else", "elif", "if", "!", "{", "time"}  # a shell word that can stand before the command it runs
REFUSAL = ("Refused: this watch wakes the session on every drain event. Run `olivercode watch REPO --until-exit` in the background, which prints one "
           "line when the drain ends. Live updates stay in the owner's terminal. See docs/RULES.md, Execution.")


def _follows(args: list[str]) -> bool:
    """True when a `tail` flag keeps it reading: -f, -F, either in a cluster, or --follow."""
    return any(a.startswith("--follow") or (a[:1] == "-" and a[1:2] != "-" and ("f" in a or "F" in a)) for a in args)


def reason(data: dict) -> str:
    """The refusal for a Monitor or background Bash call that follows the run log or runs plain `olivercode watch`, or an empty string."""
    tool, tool_input = data.get("tool_name"), data.get("tool_input") or {}
    if not (tool == "Monitor" or (tool == "Bash" and tool_input.get("run_in_background"))):
        return ""
    command = str(tool_input.get("command") or "")
    for _, name, args in policy._commands_with_env(command):
        looped = name in LOOPS
        while name in KEYWORDS and args:
            words = policy.unwrap(args)[1]
            name, args = (os.path.basename(words[0]), words[1:]) if words else ("", [])
        if name.startswith("python") and args:
            name, args = os.path.basename(args[0]), args[1:]
        if name == "olivercode" and args[:1] == ["watch"] and "--until-exit" not in args:
            return REFUSAL
        if RUN_LOG in command and (looped or (name == "tail" and _follows(args))):
            return REFUSAL
    return ""
