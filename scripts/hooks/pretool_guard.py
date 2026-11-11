#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash, Edit, Write, MultiEdit): the commit, placement, policy and GitHub guards in one process.

Four separate hooks each started Python and parsed the same input on every Bash call. This one parses the
input once and asks each guard in turn: commit_guard (a commit that would skip the repo's gates),
placement_guard (a clone or worktree outside its home), policy_guard (the repo's policy.json) and gh_guard
(the shared GitHub budget). A deny from any guard wins over an ask. Each guard fails open on its own bug, so
one broken guard never disables the others and never blocks a command. The guards stay runnable on their own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import commit_guard  # noqa: E402
import gh_guard  # noqa: E402
import placement_guard  # noqa: E402
import policy_guard  # noqa: E402
from lib import policy  # noqa: E402


def _safely(check, *args):
    try:
        return check(*args)
    except Exception:  # noqa: BLE001 -- fail open, one guard's bug never blocks a command or hides another guard
        return None


def verdicts(data: dict) -> list[tuple[str, str]]:
    """(decision, reason) from every guard that has an opinion, in the order the guards run."""
    command = (data.get("tool_input") or {}).get("command") or ""
    cwd = Path(data.get("cwd") or ".")
    found: list[tuple[str, str]] = []
    if command:
        if "commit" in command:
            why = _safely(commit_guard.reason, command, cwd)
            if why:
                found.append(("deny", why))
        why = _safely(placement_guard.reason, command, cwd)
        if why:
            found.append(("deny", why))
    decided = _safely(policy_guard.decide, data)
    if decided and decided[0]:
        decision, repo = decided
        _safely(policy.log_block, decision, repo)
        found.append((decision.kind, decision.reason))
    # A GitHub write is counted against the budget, so it is only asked once nothing else has refused the call.
    if command and not any(kind == "deny" for kind, _ in found):
        why = _safely(gh_guard.refusal, command)
        if why:
            found.append(("deny", why))
    return found


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return 0
    except json.JSONDecodeError:
        return 0
    found = verdicts(data)
    if found:
        kind, reason = next((v for v in found if v[0] == "deny"), found[0])
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": kind,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
