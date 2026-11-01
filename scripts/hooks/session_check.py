#!/usr/bin/env python3
"""Claude Code SessionStart hook: tells the session, once, what would silently fail here.

`olivercode health` only sees the repos in its registry and only when someone runs it.
This runs in every session, in whatever folder it starts, and names three gaps:

- the repo ships commit gates but git is not pointed at them (commits will be refused
  by commit_guard until it is fixed, so the session learns the fix up front)
- the repo is a git repo with no commit gates of its own
- a link that loads OliverCode's rules into ~/.claude is broken

It prints nothing when nothing is wrong, so a healthy session pays no context for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import repo_gates  # noqa: E402

RULE_LINKS = ("CLAUDE.md", "VOICE.md")


def notes(cwd: Path, claude_dir: Path) -> list[str]:
    out = []
    for name in RULE_LINKS:
        link = claude_dir / name
        if link.is_symlink() and not link.exists():
            out.append(f"~/.claude/{name} is a broken link, so OliverCode's rules did not load. "
                       "Run `scripts/olivercode install` from the OliverCode folder.")
    root = repo_gates.repo_root(cwd)
    if root:
        if repo_gates.has_gates(root):
            problem = repo_gates.gate_problem(root)
            if problem:
                out.append(f"In {root.name}, {problem}. Commits are refused until it is fixed: "
                           f"`git -C \"{root}\" config core.hooksPath .githooks`.")
        else:
            out.append(f"{root.name} has no commit gates of its own (no .githooks/pre-commit), "
                       "so nothing checks a commit here for secrets or broken rules.")
    return out


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    found = notes(Path(data.get("cwd") or "."), Path.home() / ".claude")
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": "OliverCode session check: " + " ".join(found)}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- a broken check must never stop a session from starting
        raise SystemExit(0)
