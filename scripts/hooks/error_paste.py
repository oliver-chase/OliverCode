#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a pasted error becomes a candidate (#716, #971).

When the owner's prompt holds a Python traceback or a "could not be read" error, the hook adds one bug candidate for the
session's repo (the exception line as the title, the paste as the body, `diagnosing-bugs` named), queues one line in the
owner queue. The candidate waits in the candidates list (candidates.py) until the owner promotes it, so the hook creates no issue. The same error pasted again files nothing. A paste that
looks like it holds a secret files nothing. Deterministic, with no model call and no network call, and it fails open on
its own error.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import candidates, cmd_owner, failure_log, local_config, repo_state  # noqa: E402



def _own_config() -> dict:
    """The backlog config of the repo that holds this hook, so no owner identifier or epic number sits in the source."""
    try:
        return local_config.backlog_config(Path(__file__).resolve().parent.parent.parent)
    except (OSError, ValueError):
        return {}


_CONFIG = _own_config()
FALLBACK_REPO = f"{_CONFIG['repoOwner']}/{_CONFIG['repoName']}" if "repoOwner" in _CONFIG and "repoName" in _CONFIG else ""
EPIC_NUMBER = _CONFIG.get("errorEpic")
EPIC = (f"{FALLBACK_REPO}#{EPIC_NUMBER}" if FALLBACK_REPO else f"#{EPIC_NUMBER}") if EPIC_NUMBER else ""
TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):\n(?:[ \t]+.*\n|\w.*\n)*?(?P<last>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)\b[^\n]*)")
UNREAD_RE = re.compile(r"^[^\n]*could not be read[^\n]*$", re.IGNORECASE | re.MULTILINE)
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S{6,}|-----BEGIN [A-Z ]*PRIVATE KEY)", re.IGNORECASE)
MAX_PASTE = 4000


def symptom(prompt: str) -> str:
    """The one-line symptom of the first error in the prompt, or "" when it holds none."""
    found = TRACEBACK_RE.search(prompt)
    if found:
        return found.group("last").strip()
    found = UNREAD_RE.search(prompt)
    return found.group(0).strip() if found else ""


def paste_of(prompt: str) -> str:
    """The error text: from the traceback header or the unread line to the end of the prompt, capped."""
    starts = [m.start() for m in (re.search(r"Traceback \(most recent call last\)", prompt), UNREAD_RE.search(prompt)) if m]
    return prompt[min(starts):][:MAX_PASTE].rstrip() if starts else ""


def body(repo: str, sym: str, paste: str) -> str:
    return (f"**As the owner**, I want the error `{sym[:120]}` diagnosed and fixed in {repo}, so that I never have to chase it myself.\n\n"
            "```gherkin\nFeature: A pasted error is fixed\n  Scenario: The error no longer occurs\n"
            "    Given the error pasted below\n    When the cause is diagnosed with the diagnosing-bugs loop and fixed\n"
            "    Then the failing step runs without that error\n    And a test covers the cause\n```\n\n"
            + (f"Epic: {EPIC}\n" if EPIC else "") + "Priority: P1. Size: S. Work type: Story.\n\n"
            "Existing coverage checked: the owner pasted the error, so the first step of the fix is a search of the repo and open issues for its symbol.\n\n"
            "Detail: run the `diagnosing-bugs` loop before changing code. Added by the error-paste hook from the owner's prompt, "
            "so the owner does not have to ask for it.\n\nPasted error:\n\n```\n" + paste + "\n```\n")


def file_story(prompt: str, session: str, cwd: str, home_seen: Path | None = None) -> str:
    """File the story for the first error in `prompt`. Returns the note for the session, or "" when nothing was filed."""
    sym, paste = symptom(prompt), paste_of(prompt)
    if not sym or SECRET_RE.search(paste):
        return ""
    repo = repo_state.origin(cwd) or FALLBACK_REPO if cwd else FALLBACK_REPO
    key = hashlib.sha256(f"{repo}\n{sym}".encode("utf-8")).hexdigest()[:16]
    seen_file = home_seen or failure_log.home() / "error-paste-seen.json"
    try:
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    if not isinstance(seen, dict) or key in seen:
        return ""
    title = f"Fix: {sym[:100]}"
    candidates.add("error-paste", repo, title, body(repo, sym, paste))
    seen[key] = {"repo": repo, "title": title, "filed": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(seen), encoding="utf-8")
    line = f'Error candidate added in {repo}: "{title}".'
    cmd_owner.note(session or "error-paste", line)
    return line + " Run `olivercode candidates` to review it."


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    text = file_story(str(data.get("prompt") or ""), str(data.get("session_id") or ""), str(data.get("cwd") or ""))
    if text:
        print(json.dumps({"systemMessage": text, "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"error_paste failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
