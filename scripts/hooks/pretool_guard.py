#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash, Edit, Write, MultiEdit, Monitor): the commit, archived, placement, policy and GitHub guards in one process.

One hook parses the input once per tool call and asks each guard in turn: commit_guard (a commit that would skip the repo's gates),
archived_guard (a commit or push in a repo GitHub archived or deleted), placement_guard (a clone or worktree outside its home), main_checkout (an edit or commit in a fleet repo's main checkout), policy_guard (the repo's policy.json) and gh_guard
(the shared GitHub budget), reset_guard (a `git reset --hard` in a main checkout or a tree with uncommitted changes), model_guard (a subagent on a model other than Sonnet that the owner never named) and watch_guard (a watch that wakes a session on every drain event).  A deny from any guard wins over an ask. Each guard fails open on its own bug, so
one broken guard never disables the others and never blocks a command.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import archived_guard  # noqa: E402
import commit_guard  # noqa: E402
import gh_guard  # noqa: E402
import memory_guard  # noqa: E402
import model_guard  # noqa: E402
import placement_guard  # noqa: E402
import policy_guard  # noqa: E402
import reset_guard  # noqa: E402
import watch_guard  # noqa: E402
from lib import failure_log, main_checkout, policy  # noqa: E402


def _safely(check, *args):
    try:
        return check(*args)
    except Exception as exc:  # noqa: BLE001 -- fail open, one guard's bug never blocks a command or hides another guard
        try:
            failure_log.record("hook-crash", f"{getattr(check, '__module__', '')}.{getattr(check, '__name__', '')}: {exc!r}", Path.cwd().name)  # bug intake reads it (#1371)
        except Exception:  # noqa: BLE001 -- the record is best effort too
            pass
        return None


def _found(found: list, gate: str, kind: str, why: str, cwd: Path) -> None:
    """Keep a guard's verdict and log it as that guard's trigger."""
    found.append((kind, why))
    _safely(failure_log.record, gate, why, cwd.name)


def verdicts(data: dict) -> list[tuple[str, str]]:
    """(decision, reason) from every guard that has an opinion, in the order the guards run."""
    command = (data.get("tool_input") or {}).get("command") or ""
    cwd = Path(data.get("cwd") or ".")
    found: list[tuple[str, str]] = []
    if command:
        if "commit" in command:
            why = _safely(commit_guard.reason, command, cwd)
            if why:
                _found(found, "commit_guard", "deny", why, cwd)
        if "git" in command:
            why = _safely(archived_guard.reason, command, cwd)
            if why:
                _found(found, "archived_guard", "deny", why, cwd)
        why = _safely(placement_guard.reason, command, cwd)
        if why:
            _found(found, "placement_guard", "deny", why, cwd)
        if "reset" in command:
            why = _safely(reset_guard.reason, command, cwd)
            if why:
                _found(found, "reset_guard", "deny", why, cwd)
    why = _safely(main_checkout.reason, data)
    if why:
        _found(found, "main_checkout_guard", "deny", why, cwd)
    why = _safely(model_guard.reason, data)
    if why:
        _found(found, "model_guard", "deny", why, cwd)
    why = _safely(watch_guard.reason, data)
    if why:
        _found(found, "watch_guard", "deny", why, cwd)
    decided = _safely(policy_guard.decide, data)
    if decided and decided[0]:
        decision, repo = decided
        _safely(policy.log_block, decision, repo, command or (data.get("tool_input") or {}).get("file_path") or "")
        found.append((decision.kind, decision.reason))
    # A GitHub write is counted against the budget, so it is only asked once nothing else has refused the call.
    if command and not any(kind == "deny" for kind, _ in found):
        why = _safely(gh_guard.check, data)
        if why:
            # A commit chained to a gh step still runs: only the gh step is held, so the verdict is an ask with the rewritten command.
            mixed = _safely(gh_guard.hold_only_gh, command, why)
            if mixed:
                data["_gh_hold"] = (why, mixed)
            _found(found, "gh_guard", "ask" if mixed else "deny", why, cwd)
    # A memory write that states a rule is refused; it comes last so another guard's reason is not hidden by it.
    why = _safely(memory_guard.reason, data)
    if why:
        _found(found, "memory_guard", "deny", why, cwd)
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
        held = data.get("_gh_hold")
        if held and kind == "ask":
            # Another guard's ask must not drop the hold, so the rewritten command runs whichever ask comes first, and every ask's reason is shown.
            reason = " ".join(r for k, r in found if k == "ask")
        out = {"hookEventName": "PreToolUse", "permissionDecision": kind, "permissionDecisionReason": reason}
        if held and kind == "ask":
            out["updatedInput"] = {**data["tool_input"], "command": held[1]}
        print(json.dumps({"hookSpecificOutput": out}))
        return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open
        raise SystemExit(0)
