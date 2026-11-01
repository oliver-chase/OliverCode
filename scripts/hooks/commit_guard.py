#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `git commit` that would skip the repo's gates.

Git's own pre-commit hook cannot catch the case where it never runs. This hook sits one
level up, in Claude Code, and refuses a commit in three cases:

- the repo ships `.githooks/pre-commit` but git is not pointed at it (see repo_gates)
- the commit passes `--no-verify` or `-n`, which skips every hook
- the command overrides `core.hooksPath` with `git -c`

A repo with no gates of its own commits normally; the session-start check names that gap.
Fails open on anything it cannot parse: a guard that blocks a legitimate commit because of
its own bug costs more than the rare case it misses.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import repo_gates  # noqa: E402

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\|")


def _commits(command: str, cwd: Path) -> list[tuple[Path, list[str], list[str]]]:
    """Each `git ... commit ...` in the command: (directory it runs in, git options, commit args)."""
    found = []
    here = cwd
    for segment in SEGMENT_SPLIT.split(command):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        while words and "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]  # leading VAR=value assignments
        if len(words) >= 2 and words[0] == "cd":
            here = (here / Path(words[1]).expanduser()).resolve()
            continue
        if not words or words[0] != "git":
            continue
        opts, i, where = [], 1, here
        while i < len(words) and words[i].startswith("-"):
            if words[i] in ("-C", "-c") and i + 1 < len(words):
                if words[i] == "-C":
                    where = (where / Path(words[i + 1]).expanduser()).resolve()
                opts += words[i:i + 2]
                i += 2
            else:
                opts.append(words[i])
                i += 1
        if i < len(words) and words[i] == "commit":
            found.append((where, opts, words[i + 1:]))
    return found


VALUE_FLAGS = set("mFCct")  # commit's short flags that take a value; letters after one are that value


def _skips_hooks(args: list[str]) -> bool:
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a == "--no-verify":
            return True
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch == "n":
                    return True
                if ch in VALUE_FLAGS:
                    skip_next = k == len(a) - 2  # the value is the next word only when the flag ends the cluster
                    break
    return False


def reason(command: str, cwd: Path) -> str:
    for where, opts, args in _commits(command, cwd):
        if _skips_hooks(args):
            return "This commit passes --no-verify, which skips the repo's commit gates. Commit without it and fix what the gates report."
        if any(opts[k] == "-c" and opts[k + 1].lower().startswith("core.hookspath") for k in range(len(opts) - 1)):
            return "This commit overrides core.hooksPath, which disables the repo's commit gates. Commit without the override."
        root = repo_gates.repo_root(where)
        if root and repo_gates.has_gates(root):
            problem = repo_gates.gate_problem(root)
            if problem:
                return (f"Refused: {problem}. Run `git -C \"{root}\" config core.hooksPath .githooks`, "
                        "then commit again so the gates run.")
    return ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        cwd = Path(data.get("cwd") or ".")
    except (json.JSONDecodeError, AttributeError):
        return 0
    if "commit" not in command:
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
    except Exception:  # noqa: BLE001 -- fail open, never block on the hook's own bug
        raise SystemExit(0)
