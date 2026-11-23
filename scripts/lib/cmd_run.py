"""Launcher command `run`: run Claude Code headless on one task in the current folder, with OliverCode's rounds and validation around it."""

from __future__ import annotations

import os
import time

from lib import agent_loop, model

USAGE = "Usage: olivercode run \"TASK\" [--max-turns N] [--model NAME]"


def command_run(argv: list[str]) -> int:
    task_parts, max_turns, name, i = [], 30, "", 0
    while i < len(argv):
        if argv[i] in ("--max-turns", "--model") and i + 1 < len(argv):
            if argv[i] == "--model":
                name = argv[i + 1]
            else:
                try:
                    max_turns = int(argv[i + 1])
                except ValueError:
                    print(USAGE)
                    return 1
            i += 2
        elif argv[i].startswith("--"):
            print(USAGE)
            return 1
        else:
            task_parts.append(argv[i])
            i += 1
    task = " ".join(task_parts).strip()
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
