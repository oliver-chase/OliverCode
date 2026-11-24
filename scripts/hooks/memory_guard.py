#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Edit, Write, MultiEdit, Bash): refuses a write that puts a rule into memory.

Rules belong in a skill, a check or a story. Memory holds the owner's preferences and session state, so an entry written
into .claude-optimization/memory that states a rule is refused, whatever story number or path it cites. Auto-memory under
~/.claude/projects is never written. A MEMORY.md line that only adds a pointer link is exempt. A shell write is read from the
parsed command words, so a quoted path or a comment names no target. Fails open with one stderr line on any error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MEMORY_PATH = re.compile(r"(?:\.claude-optimization/memory/|\.claude/projects/[^/\s'\"]+/memory/)")
AUTO_MEMORY = re.compile(r"\.claude/projects/[^/\s'\"]+/memory/")
# A rule is a line that starts with an imperative (or a sentence or a quoted string does); a fact that holds should or always mid-sentence is allowed.
RULE = re.compile(r"(?:^|[.!?]\s+|['\"])[\s>#*\-\d.)]*(?:always|never|must|should|shall|whenever|do not|don'?t|before (?:you|each|every|any)|from now on)\b", re.IGNORECASE | re.MULTILINE)
POINTER_LINE = re.compile(r"^\s*(?:[-*]\s*)?\[[^\]]+\]\([^)]+\)(?:\s*[-:—].*)?$")

REFUSAL = ("Refused: this write puts a rule into memory, and auto-memory under ~/.claude/projects is never written. Rules belong "
           "in the skill, check or story. See docs/RULES.md, Documents.")


def _written(tool_input: dict) -> str:
    """The text a file tool adds to its target."""
    edits = [e.get("new_string") or "" for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    return "\n".join([tool_input.get("content") or "", tool_input.get("new_string") or "", *edits])


def _only_pointers(path: str, text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return Path(path).name == "MEMORY.md" and bool(lines) and all(POINTER_LINE.match(line) for line in lines)


def _shell_targets(command: str) -> list[str]:
    """The memory paths a parsed shell command writes: redirect, tee, cp, mv and `sed -i` targets."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lib import policy, policy_parse
    found = []
    for words in policy_parse.lex_uncommented(command):
        name, rest = policy_parse._head(words)
        found += [t for t in policy._write_targets(name, rest) if MEMORY_PATH.search(t.replace("\\", "/"))]
    return found


def reason(data: dict) -> str:
    """The refusal for a memory write that states a rule or lands in auto-memory, or an empty string."""
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if path:
        if not MEMORY_PATH.search(path.replace("\\", "/")):
            return ""
        text = _written(tool_input)
        if _only_pointers(path, text):
            return ""
        targets = [path]
    else:
        text = tool_input.get("command") or ""
        try:
            targets = _shell_targets(text)
        except ValueError:
            return ""
        if not targets:
            return ""
    if any(AUTO_MEMORY.search(t.replace("\\", "/")) for t in targets):
        return REFUSAL
    return REFUSAL if RULE.search(text) else ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
        why = reason(data) if isinstance(data, dict) else ""
    except Exception as exc:  # noqa: BLE001 -- fail open
        print(f"memory_guard: skipped, {exc}", file=sys.stderr)
        return 0
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- fail open
        print(f"memory_guard: skipped, {exc}", file=sys.stderr)
        raise SystemExit(0)
