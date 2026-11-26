#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash, Edit, Write): enforces the repo's .olivercode/policy.json.

A command or path outside the policy is denied with the rule that applies, and a trigger (a push,
a mass delete) asks first. Each decision is written to the
failure log. A repo with no policy is not restricted. Fails open on anything it cannot parse, because
a guard that blocks a legitimate action on its own bug costs more than the case it misses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "lib"))
import repo_gates  # noqa: E402
from lib import policy  # noqa: E402


def decide(data: dict) -> tuple[policy.Decision | None, str]:
    cwd = Path(data.get("cwd") or ".")
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    base = Path(file_path).parent if file_path and Path(file_path).is_absolute() else cwd
    # A write into a folder that does not exist yet belongs to the repo of its nearest existing folder.
    while not base.is_dir() and base != base.parent:
        base = base.parent
    root = repo_gates.repo_root(base)
    if not root:
        return None, ""
    rules = policy.load(root)
    if not rules:
        return None, root.name
    if file_path:
        return policy.evaluate_path(rules, root, file_path), root.name
    command = tool_input.get("command") or ""
    return (policy.evaluate_bash(rules, command, root.name, root) if command else None), root.name


def main() -> int:
    try:
        data = json.load(sys.stdin)
        decision, repo = decide(data)
    except (json.JSONDecodeError, AttributeError, OSError):
        return 0
    if decision:
        policy.log_block(decision, repo)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": decision.kind,
                                                 "permissionDecisionReason": decision.reason}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
