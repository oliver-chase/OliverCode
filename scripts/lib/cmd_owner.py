"""Launcher command `owner`: the one queue of steps only the owner can take (#629).

~/.olivercode/owner-queue.jsonl (OLIVERCODE_HOME overrides the folder) holds one JSON line per change:

    {"id": 1, "created": "...", "session": "SID", "step": "...", "command": "...", "error": "...", "status": "open"}

A step is queued with the command the session ran and the error it returned, marked a decision the session
could not make, or prepared to its final screen: the signed-in browser tab where only the owner's secret and submit
remain, what happens after submit and how to check the result (#635). A secret in any field is refused. `done ID` appends a line with the same id and status done, and the latest line per id wins.
`summary` prints the open steps and what changed in the last seven days, with no model call. Standard library only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import failure_log
from lib.cli import flags as _flags

USAGE = """Usage:
  olivercode owner add --session SID --step "TEXT" (--command "CMD" --error "ERROR" | --decision)
  olivercode owner add --session SID --step "TEXT" --tab URL --after "WHAT HAPPENS AFTER SUBMIT" [--check "HOW TO VERIFY"]
  olivercode owner list
  olivercode owner done ID
  olivercode owner summary"""
WEEK = timedelta(days=7)
OWNER_PREFIX = "Owner ·"


def path() -> Path:
    return failure_log.home() / "owner-queue.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lines() -> list[dict]:
    p = path()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            out.append(item)
    return out


def _append(item: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item) + "\n")


def items() -> list[dict]:
    """The latest line per id, in id order. A done line keeps the step, command and error of the line it closes."""
    latest: dict[int, dict] = {}
    for line in _lines():
        latest[line["id"]] = {**latest.get(line["id"], {}), **line}
    return [latest[i] for i in sorted(latest)]


# A card number, or a password, key, token or code written into a field, which no agent ever types or stores (#635). The keyword
# needs a non-letter before it, so a repo name such as OliverCode: is not read as a code (#973).
_SECRET = re.compile(r"\b(?:\d[ -]?){13,19}\b|(?<![A-Za-z])(?:password|passwd|passcode|pwd|secret|token|api[_-]?key|otp|code|cvv)\s*[=:]\s*\S", re.IGNORECASE)


def add(session: str, step: str, command: str = "", error: str = "", tab: str = "", after: str = "", check: str = "",
        extra: dict | None = None) -> dict:
    """Queue one step. Refused unless it carries the command tried and its error, is a decision, or is prepared to its final screen
    (a tab, and what happens after submit)."""
    if not session.strip() or not step.strip():
        raise ValueError("a step needs the session and the step text")
    if any(_SECRET.search(v) for v in (step, command, error, tab, after, check)):
        raise ValueError("a step never holds a password, card number, key or code")
    if bool(tab.strip()) != bool(after.strip()):
        raise ValueError("a prepared step carries its tab and what happens after submit together")
    if tab.strip() and (command.strip() or error.strip()):
        raise ValueError("a prepared step is the tab and the after-submit line, not a command and error")
    if tab.strip():
        nxt = max((i["id"] for i in _lines()), default=0) + 1
        item = {"id": nxt, "created": _now().isoformat(timespec="seconds"), "session": session, "step": step,
                "command": "", "error": "", "tab": tab, "after": after, "check": check, "status": "open"}
        _append(item)
        return item
    if bool(command.strip()) != bool(error.strip()):
        raise ValueError("a step carries the command tried and its error together")
    nxt = max((i["id"] for i in _lines()), default=0) + 1
    item = {"id": nxt, "created": _now().isoformat(timespec="seconds"), "session": session, "step": step,
            "command": command, "error": error, "status": "open", **(extra or {})}
    _append(item)
    return item


def close(item_id: int) -> None:
    _append({"id": item_id, "status": "done", "closed": _now().isoformat(timespec="seconds")})


def queue_denied(session: str, key: str, step: str, command: str, error: str, resolve: dict) -> dict | None:
    """The one writer for a step the permission classifier denied (#781, #787): one open line per key, carrying the exact
    command and the `resolve` check that closes it. Returns None when the key already has an open line."""
    if any(i["status"] == "open" and i.get("key") == key for i in items()):
        return None
    return add(session, step, command, error, extra={"key": key, "resolve": resolve})


def note(session: str, step: str) -> dict:
    """A line the owner can read and never has to close: a job's result, queued with status info."""
    nxt = max((i["id"] for i in _lines()), default=0) + 1
    item = {"id": nxt, "created": _now().isoformat(timespec="seconds"), "session": session, "step": step,
            "command": "", "error": "", "status": "info"}
    _append(item)
    return item


def _show(item: dict) -> str:
    if item.get("tab"):
        return (f"  #{item['id']} {item['step']} (prepared at {item['tab']}: you enter the secret and submit, then the agent {item['after']}"
                f"; session {item['session']}, {item['created'][:10]})")
    how = f"tried `{item['command']}`: {item['error']}" if item.get("command") else "a decision only the owner can make"
    return f"  #{item['id']} {item['step']} ({how}; session {item['session']}, {item['created'][:10]})"


def waiting_steps(session: str) -> str:
    """The two calls that make a session waiting on the owner easy to find: an "Owner ·" title and a pin (#649)."""
    return (f'Title: call set_session_title for {session} with "{OWNER_PREFIX}" in front of its current title.\n'
            f"Pin: call set_pinned for {session} with pinned=true.")


def answered_steps(session: str) -> str:
    """The calls that undo waiting_steps once the owner has answered: the prefix comes off and the pin returns to the session's role."""
    return (f'Title: call set_session_title for {session} with its title without the "{OWNER_PREFIX}" prefix.\n'
            f"Pin: call set_pinned for {session} with pinned=false.")


def resume_steps(item: dict) -> str:
    """What the agent does once the owner says a prepared step is done: check the result, then carry on (#635)."""
    check = item.get("check") or "the page in the tab or the service's API"
    return f"Resume: check the result in {check}, then carry on with the work that waited on it: {item.get('after')}."


def summary() -> str:
    every = items()
    open_items = [i for i in every if i["status"] == "open"]
    cutoff = _now() - WEEK
    added = [i for i in every if datetime.fromisoformat(i["created"]) >= cutoff]
    done = [i for i in every if i["status"] == "done" and i.get("closed", "") >= cutoff.isoformat(timespec="seconds")]
    head = f"Owner queue: {len(open_items)} open, {len(added)} added and {len(done)} done in the last seven days."
    return "\n".join([head, *(_show(i) for i in open_items)]) if open_items else head + " Nothing waits on you."


def command_owner(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    if sub == "add":
        parsed = _flags(rest, {"--session", "--step", "--command", "--error", "--tab", "--after", "--check"}, {"--decision"})
        if parsed is None or parsed[2]:
            print(USAGE)
            return 1
        vals, _, _, flags = parsed
        decision = "--decision" in flags
        prepared = bool(vals.get("--tab") or vals.get("--after"))
        if prepared and decision or (not prepared and decision == bool(vals.get("--command") or vals.get("--error"))):
            print("Refused: queue a step with the command tried and its error, with --decision, or with --tab and --after. Nothing was written.")
            return 1
        try:
            item = add(vals.get("--session", ""), vals.get("--step", ""), vals.get("--command", ""), vals.get("--error", ""),
                       vals.get("--tab", ""), vals.get("--after", ""), vals.get("--check", ""))
        except ValueError as exc:
            print(f"Refused: {exc}. Nothing was written.")
            return 1
        print(f"Queued owner step #{item['id']} in {path()}")
        print(waiting_steps(item["session"]))
        return 0
    if sub == "list" and not rest:
        open_items = [i for i in items() if i["status"] == "open"]
        print("\n".join(_show(i) for i in open_items) if open_items else "Nothing waits on the owner.")
        return 0
    if sub == "done" and len(rest) == 1 and rest[0].isdigit():
        found = next((i for i in items() if i["id"] == int(rest[0]) and i["status"] == "open"), None)
        if not found:
            print(f"No open owner step #{rest[0]}.")
            return 1
        close(found["id"])
        print(f"Closed owner step #{found['id']}")
        if found.get("tab"):
            print(resume_steps(found))
        if not any(i["status"] == "open" and i["session"] == found["session"] for i in items()):
            print(answered_steps(found["session"]))
        return 0
    if sub == "summary" and not rest:
        print(summary())
        return 0
    print(USAGE)
    return 1
