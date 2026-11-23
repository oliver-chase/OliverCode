"""Correction flags: the owner corrected a session, and a lesson must follow.

The UserPromptSubmit hook `lesson_capture.py` writes one small file per correction into
~/.olivercode/lesson-flags/ (OLIVERCODE_HOME overrides the folder). `olivercode lesson add` clears the oldest flag (or the one named
with `--flag`), and `olivercode health` fails when one is more than a day old with no lesson after it.
A flag holds the time and a short snippet around the phrase, never the full prompt. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from lib import failure_log

PHRASES = ("never", "don't like", "not good", "why can't you", "i told you", "wrong again", "again and again", "not again",
           "stop doing", "wrong",
           "that's not what i")
# A prompt that starts like this came from another session or the system, so the owner did not type it.
SKIP_PREFIXES = ("<cross-session-message", "[cross-session-message", "<system-notification", "[system-notification",
                 "system-notification:", "<system-reminder", "<task-notification", "<side-sessions-event", "<ci-monitor-event",
                 "[system notification", "another claude session sent a message", "<agent-message", "[subagent hand-back]",
                 "<scheduled-task", "background (from the session that started this one)")
# Text the owner pasted is someone else's words, usually another session's report, so it is not the owner's correction.
_PASTED = re.compile(r"<pasted_content\b[^>]*>.*?(</pasted_content[^>]*>|$)", re.S | re.I)
SNIPPET_CHARS = 60
STALE_SECONDS = 24 * 3600


def folder() -> Path:
    return failure_log.home() / "lesson-flags"


def from_owner(prompt: str) -> bool:
    """True when the owner typed the prompt: it is not a message from another session, a notification or a hand-back."""
    text = (prompt or "").lstrip().lower()
    return bool(text) and not text.startswith(SKIP_PREFIXES) and "another claude session sent a message" not in text[:300]


def match(prompt: str) -> str | None:
    """The first correction phrase in an owner prompt, or None for no phrase or a message from another session."""
    text = (prompt or "").lstrip().lower().replace("’", "'")
    if not text or text.startswith(SKIP_PREFIXES) or "another claude session sent a message" in text[:300]:
        return None
    text = _PASTED.sub(" ", text)
    for phrase in PHRASES:
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text):
            return phrase
    return None


def snippet(prompt: str, phrase: str) -> str:
    text = " ".join(_PASTED.sub(" ", (prompt or "").replace("’", "'")).split())
    at = text.lower().find(phrase)
    start = max(0, at - SNIPPET_CHARS // 2) if at >= 0 else 0
    return text[start:start + SNIPPET_CHARS]


def record(prompt: str, now: float | None = None) -> Path | None:
    """Write a flag when the prompt holds a correction phrase. Returns the flag file or None."""
    phrase = match(prompt)
    if phrase is None:
        return None
    stamp = time.time() if now is None else now
    target = folder()
    target.mkdir(parents=True, exist_ok=True)
    flag = target / f"{int(stamp)}-{uuid.uuid4().hex[:8]}.json"
    flag.write_text(json.dumps({"time": stamp, "phrase": phrase, "snippet": snippet(prompt, phrase)}), encoding="utf-8")
    return flag


def open_flags() -> list[tuple[Path, float]]:
    """Every open flag as (file, time), oldest first. An unreadable file counts as the age of the file."""
    out = []
    if folder().is_dir():
        for p in folder().glob("*.json"):
            try:
                out.append((p, float(json.loads(p.read_text(encoding="utf-8"))["time"])))
            except (OSError, ValueError, KeyError, TypeError):
                try:
                    out.append((p, p.stat().st_mtime))
                except OSError:
                    continue
    return sorted(out, key=lambda item: item[1])


def clear(name: str | None = None) -> str | None:
    """Delete the one flag a lesson answers: the flag whose file name holds `name`, else the oldest. Returns its file
    name, or None when no flag matches. Every other flag stays open."""
    for p, _ in open_flags():
        if name is None or name in p.name:
            try:
                p.unlink()
                return p.name
            except OSError:
                return None
    return None


def dismiss(name: str, reason: str, now: float | None = None) -> str:
    """Close one flag whose text is not an owner correction, and log the flag and the reason in dismissed.jsonl beside
    the flags. Returns the flag's file name. Raises ValueError for an empty reason or a name that matches no open flag."""
    if not (reason or "").strip():
        raise ValueError("a dismissal needs --reason saying why the flag is not an owner correction")
    for p, _ in open_flags():
        if name and name in p.name:
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                body = {}
            entry = {"flag": p.name, "snippet": body.get("snippet", ""), "reason": reason.strip(),
                     "dismissed": time.time() if now is None else now}
            with (folder() / "dismissed.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            p.unlink()
            return p.name
    raise ValueError(f"no open correction flag matches {name!r}")


def stale_count(now: float | None = None) -> int:
    """How many open flags are more than a day old."""
    current = time.time() if now is None else now
    return sum(1 for _, stamp in open_flags() if current - stamp > STALE_SECONDS)


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
