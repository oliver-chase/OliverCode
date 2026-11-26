"""Who typed a prompt, and what covers a lesson.

`from_owner` tells an owner's prompt from a message another session or the system sent, for the hooks that act on the owner's words.
`check_ref` decides whether a test path or an open story may cover a lesson. Standard library only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# A prompt that starts like this came from another session or the system, so the owner did not type it.
SKIP_PREFIXES = ("<cross-session-message", "[cross-session-message", "<system-notification", "[system-notification",
                 "system-notification:", "<system-reminder", "<task-notification", "<side-sessions-event", "<ci-monitor-event",
                 "[system notification", "another claude session sent a message", "<agent-message", "[subagent hand-back]",
                 "<scheduled-task", "background (from the session that started this one)")

def from_owner(prompt: str) -> bool:
    """True when the owner typed the prompt: it is not a message from another session, a notification or a hand-back."""
    text = (prompt or "").lstrip().lower()
    return bool(text) and not text.startswith(SKIP_PREFIXES) and "another claude session sent a message" not in text[:300]


# Covering a lesson: a test file that exists in the repo, or a story that is still open.
_TEST_PATH = re.compile(r"(^|/)tests?/.+\.py$|(^|/)test_[^/]+\.py$")
_STORY = re.compile(r"#?(\d+)")


def story_state(number: int) -> str:
    """The state of a story as `gh issue view N --json state` reports it, or "" when gh cannot say."""
    import subprocess
    try:
        run = subprocess.run(["gh", "issue", "view", str(number), "--json", "state"], capture_output=True,
                             text=True, timeout=30)
        return str(json.loads(run.stdout).get("state", "")).upper() if run.returncode == 0 else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def check_ref(ref: str, repo: str | Path | None, state=story_state) -> str:
    """"" when REF is acceptable as the cover for a lesson, otherwise the reason it is refused."""
    ref = (ref or "").strip()
    story = _STORY.fullmatch(ref)
    if story:
        found = state(int(story.group(1)))
        if found == "OPEN":
            return ""
        return (f"story #{story.group(1)} is closed, so it cannot cover a lesson" if found == "CLOSED"
                else f"story #{story.group(1)} could not be checked, so it cannot cover a lesson")
    if _TEST_PATH.search(ref) and ".." not in Path(ref).parts:
        root = Path(repo if repo is not None else ".")
        return "" if (root / ref).is_file() else f"the test {ref} does not exist in {root}"
    return "a lesson is covered only by a test path that exists (tests/... or skills/.../test_*.py) or an open story number"
