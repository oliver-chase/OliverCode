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
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import failure_log
from lib.cli import flags as _flags

USAGE = """Usage:
  olivercode owner add --session SID --step "TEXT" (--command "CMD" --error "ERROR" | --decision)
  olivercode owner add --session SID --step "TEXT" --tab URL --after "WHAT HAPPENS AFTER SUBMIT" [--check "HOW TO VERIFY"]
  olivercode owner list
  olivercode owner show ID
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


def _expire_notes() -> None:
    """Drop info notes older than a week from the file, so the queue does not grow by the notes of every night (#1024)."""
    p = path()
    if not p.is_file():
        return
    cutoff = (_now() - WEEK).isoformat(timespec="seconds")
    rows = [l for l in p.read_text(encoding="utf-8").splitlines()]

    def stale(line: str) -> bool:
        try:
            row = json.loads(line)
        except ValueError:
            return False
        return isinstance(row, dict) and row.get("status") == "info" and str(row.get("created", "")) < cutoff

    if not any(stale(l) for l in rows):
        return
    with failure_log.locked(p):
        kept = [l for l in p.read_text(encoding="utf-8").splitlines() if not stale(l)]
        failure_log.write_private(p, "".join(l + "\n" for l in kept))


def items() -> list[dict]:
    """The latest line per id, in id order. A done line keeps the step, command and error of the line it closes. An info note older than seven days is dropped from the file first."""
    try:
        _expire_notes()
    except OSError:
        pass
    latest: dict[int, dict] = {}
    for line in _lines():
        latest[line["id"]] = {**latest.get(line["id"], {}), **line}
    return [latest[i] for i in sorted(latest)]


# A card number, or a password, key, token or code written into a field, which no agent ever types or stores (#635). The keyword
# needs a non-letter before it, so a repo name such as OliverCode: is not read as a code (#973).
_SECRET = re.compile(r"\b(?:\d[ -]?){13,19}\b|(?<![A-Za-z])(?:password|passwd|passcode|pwd|secret|token|api[_-]?key|otp|code|cvv)\s*[=:]\s*\S", re.IGNORECASE)


def _held(lines: list[dict], session: str, step: str) -> dict | None:
    """The open item for the same session and step text, merged across its lines, or None."""
    latest: dict[int, dict] = {}
    for line in lines:
        latest[line["id"]] = {**latest.get(line["id"], {}), **line}
    return next((i for i in latest.values() if i.get("status") == "open" and i.get("session") == session and i.get("step") == step), None)


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
    if not tab.strip() and bool(command.strip()) != bool(error.strip()):
        raise ValueError("a step carries the command tried and its error together")
    with failure_log.locked(path()):  # the next id and the append are one step, so two writers never share an id
        every = _lines()
        held = _held(every, session, step)
        if held is not None:  # the same ask again counts the repeat and queues nothing new (#1205)
            _append({"id": held["id"], "repeats": int(held.get("repeats", 1)) + 1, "status": "open"})
            return {**held, "repeats": int(held.get("repeats", 1)) + 1}
        nxt = max((i["id"] for i in every), default=0) + 1
        if tab.strip():
            item = {"id": nxt, "created": _now().isoformat(timespec="seconds"), "session": session, "step": step,
                    "command": "", "error": "", "tab": tab, "after": after, "check": check, "status": "open"}
        else:
            item = {"id": nxt, "created": _now().isoformat(timespec="seconds"), "session": session, "step": step,
                    "command": command, "error": error, "status": "open", **(extra or {})}
        _append(item)
    return item


def close(item_id: int, reason: str = "") -> None:
    _append({"id": item_id, "status": "done", "closed": _now().isoformat(timespec="seconds"), **({"reason": reason} if reason else {})})


def add_once(session: str, key: str, step: str, command: str, error: str, prefix: str = "") -> dict:
    """One open item per KEY. A second call with the key open rewrites its step to the latest (a new count) and queues nothing new.
    An older open item with no key whose step begins with PREFIX counts as the same subject (#1024)."""
    held = next((i for i in items() if i["status"] == "open" and (i.get("key") == key or (prefix and not i.get("key") and i["step"].startswith(prefix)))), None)
    if held is None:
        return add(session, step, command, error, extra={"key": key})
    if held["step"] != step:
        _append({"id": held["id"], "step": step, "command": command, "error": error, "status": "open"})
    return {**held, "step": step}


def close_where(test, reason: str) -> list[int]:
    """Mark done, with REASON, every open item TEST accepts. Returns their ids."""
    done = [i["id"] for i in items() if i["status"] == "open" and test(i)]
    for n in done:
        close(n, reason)
    return done


def story_of(item: dict) -> int | None:
    """The story an item waits on: its story field, else the number in a step that begins "Story #N"."""
    if isinstance(item.get("story"), int):
        return item["story"]
    found = re.match(r"Story #(\d+) ", item.get("step") or "")
    return int(found.group(1)) if found else None


def story_closed(slug: str, number: int) -> bool:
    """True when the story reads closed over REST. A story that cannot be read counts as still open."""
    try:
        done = subprocess.run(["gh", "api", f"repos/{slug}/issues/{number}", "--jq", ".state"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and done.stdout.strip() == "closed"


def clear_stories(slug: str, closed=story_closed, only: int | None = None) -> list[int]:
    """Close the open items that wait on a story now closed. An item whose key names another repo is left alone."""
    def test(item: dict) -> bool:
        n = story_of(item)
        if n is None or (only is not None and n != only):
            return False
        other = re.match(r"policy-stop:(.+)#\d+$", item.get("key") or "")
        return (other.group(1) == slug if other else True) and closed(slug, n)
    return close_where(test, "the story is closed")


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


def _brief(text: str, width: int = 100) -> str:
    """The first line of a step, cut at a word with an ellipsis when it is longer than width (#1177)."""
    line = (text or "").splitlines()[0].strip() if (text or "").strip() else ""
    return line if len(line) <= width else line[:width].rsplit(" ", 1)[0] + "…"


# Plain titles for who raised a step, in the order the owner should read them: decisions first, upkeep last (#1177).
TITLES = (("groom", "Decisions about your boards"), ("drain", "Stories stopped and waiting for you"), ("dispatch", "Stories stopped and waiting for you"),
          ("gh-replay", "GitHub writes that failed"), ("status-page", "City page"), ("conform", "Repos that do not match the standard"),
          ("fleet-sync", "Repos that could not catch up with GitHub"), ("maintain", "Machine upkeep"))


_PATHS = re.compile(r"(?:/[\w.~-]+){2,}|[0-9a-f]{12,}|#\d+")


def _shape(item: dict) -> str:
    """A step with its paths, hashes and numbers blanked and its subject word dropped, so two steps about the same thing share a key."""
    return re.sub(r"^\w+ (?:health|suite|placement|tidy|branches|synced|docs): ", "", _PATHS.sub("…", _brief(item["step"], 400))).strip()


def listing(open_items: list[dict]) -> str:
    """The open steps under plain headings, the count first, one line each (#1177). A prepared step keeps its tab and after-submit line.
    `owner show ID` prints the command tried and its error."""
    if not open_items:
        return "Nothing is waiting on you."
    order = {who: n for n, (who, _) in enumerate(TITLES)}
    titles = dict(TITLES)
    groups: dict[str, list[dict]] = {}
    for item in open_items:
        who = item.get("session") or "other"
        groups.setdefault(titles.get(who, f"From {who}"), []).append(item)
    rank = {title: min([order[w] for w, t in TITLES if t == title] or [99]) for title in groups}
    out = [f"{len(open_items)} thing{'s' if len(open_items) != 1 else ''} waiting on you", "", "Next: `olivercode owner show NUMBER` gives the detail of one, and `olivercode owner done NUMBER` clears it once it is handled.", ""]
    for title in sorted(groups, key=lambda t: (rank[t], t)):
        rows = groups[title]
        out.append(f"{title} ({len(rows)})")
        alike: dict[str, list[dict]] = {}
        for i in rows:
            alike.setdefault(_shape(i) if not i.get("tab") else f"tab{i['id']}", []).append(i)
        for same in alike.values():
            i = same[0]
            if len(same) > 1:  # steps that differ only in a path or a number are one line with their numbers (#1177)
                out.append(f"  {len(same)} like this: {_brief(_PATHS.sub('…', i['step']), 80)} (" + ", ".join(f"#{j['id']}" for j in same) + ")")
                continue
            repeat = f"  (raised {i['repeats']} times)" if int(i.get("repeats", 1)) > 1 else ""
            out.append(_show(i) if i.get("tab") else f"  #{i['id']:<4} {_brief(i['step'])}{repeat}")
        out.append("")
    return "\n".join(out).rstrip()


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
        print(listing([i for i in items() if i["status"] == "open"]))
        return 0
    if sub == "show" and len(rest) == 1 and rest[0].isdigit():
        found = next((i for i in items() if i["id"] == int(rest[0])), None)
        print(_show(found) if found else f"No owner step #{rest[0]}.")
        return 0 if found else 1
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
