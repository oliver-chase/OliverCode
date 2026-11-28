#!/usr/bin/env python3
"""Claude Code PreToolUse hook helper (Agent): keeps a subagent on Sonnet unless the owner named another model.

Delegated work runs on Sonnet. The owner names another model in chat and that model then holds for the session, so the
guard reads the owner's messages in the session transcript and allows the model they mention. An Agent call with
Sonnet always passes. A general-purpose or untyped call with no model would inherit the thread's model, so it is given
Sonnet unless the owner named Opus; any other subagent type keeps its definition's model. Fails open on any error and on
an unreadable transcript.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

AGENT_TOOLS = {"Agent", "Task"}
FAMILIES = ("opus", "haiku", "fable")


def _family(model: str) -> str:
    """The model family a name stands for, such as opus for claude-opus-4-1, or the lowercased name when it is none of them."""
    name = model.strip().lower()
    return next((f for f in (*FAMILIES, "sonnet") if f in name), name)


def _owner_text(transcript: str) -> str:
    """Everything the owner typed in this session, with tool results left out."""
    lines = []
    with Path(transcript).open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                lines.append(content)
            elif isinstance(content, list):
                lines.extend(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return "\n".join(lines)


def _owner_named(data: dict, family: str) -> bool:
    """Whether the owner mentioned this model family in the session."""
    transcript = str(data.get("transcript_path") or "")
    return bool(transcript and re.search(rf"\b{re.escape(family)}\b", _owner_text(transcript), re.I))


def default_input(data: dict) -> dict | None:
    """The input of a general-purpose or untyped Agent call with no model, with Sonnet added, or None to leave the call as it is."""
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") not in AGENT_TOOLS or tool_input.get("model"):
        return None
    if tool_input.get("subagent_type") not in (None, "", "general-purpose") or _owner_named(data, "opus"):
        return None
    return {**tool_input, "model": "sonnet"}


def reason(data: dict) -> str:
    """The refusal for an Agent call on a non-Sonnet model the owner did not name, or an empty string."""
    if data.get("tool_name") not in AGENT_TOOLS:
        return ""
    model = str((data.get("tool_input") or {}).get("model") or "")
    family = _family(model)
    if not model or family == "sonnet" or _owner_named(data, family):
        return ""
    return (f"Delegated work runs on Sonnet unless the owner names {model}. Start the subagent on Sonnet, or leave the model "
            "out. See docs/RULES.md, Execution.")
