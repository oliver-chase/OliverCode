"""Launcher command `run`: run Claude Code headless on one task in the current folder, with OliverCode's rounds and validation around it."""

from __future__ import annotations

import os
import time

from lib import agent_loop, model
from lib.cli import flags

USAGE = "Usage: olivercode run \"TASK\" [--max-turns N] [--model NAME]"


def command_run(argv: list[str]) -> int:
    parsed = flags(argv, {"--max-turns", "--model"})
    try:
        max_turns = int(parsed[0].get("--max-turns", 30)) if parsed else 0
    except ValueError:
        max_turns = 0
    name, task = (parsed[0].get("--model", ""), " ".join(parsed[2]).strip()) if parsed else ("", "")
    if not task or max_turns < 1:
        print(USAGE)
        return 1
    cwd = os.getcwd()
    session = f"run-{int(time.time())}"
    if not model.available():
        print("Error: the claude command is not on PATH. Install Claude Code and sign in with `claude`.")
        return 1
    outcome = agent_loop.run_loop(task, cwd, session, max_turns=max_turns, model_name=name)
    print(f"{'Done' if outcome['done'] else 'Stopped'}: {outcome['reason']} {outcome['rounds']} rounds, about {outcome['tokens']:,} tokens.")
    return 0 if outcome["done"] else 1
