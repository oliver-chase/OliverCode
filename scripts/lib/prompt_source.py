"""Who typed a prompt: `from_owner` tells an owner's prompt from a message another session or the system sent, for the hooks that act on the owner's words. Standard library only."""

from __future__ import annotations

# A prompt that starts like this came from another session or the system, so the owner did not type it.
SKIP_PREFIXES = ("<cross-session-message", "[cross-session-message", "<system-notification", "[system-notification",
                 "system-notification:", "<system-reminder", "<task-notification", "<side-sessions-event", "<ci-monitor-event",
                 "[system notification", "another claude session sent a message", "<agent-message", "[subagent hand-back]",
                 "<scheduled-task", "background (from the session that started this one)")

def from_owner(prompt: str) -> bool:
    """True when the owner typed the prompt: it is not a message from another session, a notification or a hand-back."""
    text = (prompt or "").lstrip().lower()
    return bool(text) and not text.startswith(SKIP_PREFIXES) and "another claude session sent a message" not in text[:300]
