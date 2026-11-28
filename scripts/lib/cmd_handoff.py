"""Launcher command `handoff`: one live handoff per project, deleted once the next thread has read it (#1321).

`olivercode handoff write PROJECT FILE` files FILE as PROJECT-handoff-DATE.md in the handoff folder and deletes the project's other handoffs, then prints the
desktop-app calls that start, name and pin the next thread and unpin this one (#1488). It starts nothing itself.
`olivercode handoff read PROJECT` prints the handoff and deletes it, with no archive copy. A thread with no number yet gets the calls that name it
"PROJECT N", N from 1 to 10 (#1353), and pin it. The thread that takes the number `write` reserved makes
them only when its title or pin is missing. Only regular files named PROJECT-handoff-*.md count, so
another project's handoffs and a folder that merely holds the word are left alone. Before write files anything it parses each `olivercode drain`
and `olivercode dispatch` command in FILE, without running one, and refuses a handoff whose command would print a usage error.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from lib import cmd_dispatch, cmd_drain, cmd_owner, failure_log

USAGE = "Usage: olivercode handoff write PROJECT FILE | olivercode handoff read PROJECT"
COMMAND_RE = re.compile(r"`olivercode\s+(drain|dispatch)\b([^`\n]*)`")  # a backticked command, never a sentence that names one
FENCED_RE = re.compile(r"\s*(?:\$\s*)?olivercode\s+(drain|dispatch)\b(.*)")  # a whole line inside a code fence
THREAD_NUMBERS = "thread-numbers.json"  # project -> last thread number, in the OliverCode home, never in the handoff folder
THREAD_SESSIONS = "thread-sessions.json"  # each session's thread number, each project's pinned session and what `write` reserved for `read`
KEEP_SESSIONS = 20


def handoff_dir() -> Path:
    return Path(os.environ.get("OLIVERCODE_HANDOFF_DIR") or Path.cwd()).expanduser()


def handoffs(project: str, folder: Path) -> list[Path]:
    """The project's handoff files in `folder`, newest first. A folder or a name for another project is not one."""
    pattern = re.compile(rf"{re.escape(project)}-handoff-.+\.md")
    found = [p for p in folder.glob("*.md") if p.is_file() and pattern.fullmatch(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def session() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def unpin_step(old: str) -> str:
    """The pin call that takes the pin from session `old`, '' when its id is unknown. An open owner-queue item that names it keeps its pin."""
    if not old:
        return "Pin: call set_pinned for this session with pinned=false, unless `olivercode owner list` shows an open item for this session."
    if any(i["session"] == old for i in cmd_owner.open_items()):
        return f"Pin: an open owner-queue item names {old}, so leave it pinned."
    return f"Pin: call set_pinned for {old} with pinned=false."


def name_steps(project: str, number: int, sid: str, old: str) -> list[str]:
    """The calls that give a thread its title and the pin, and take the pin from `old`, the session that held it."""
    who = sid or "this session"
    steps = [f'Title: call set_session_title for {who} with "{project} {number}", keeping an "{cmd_owner.OWNER_PREFIX}" prefix in front if its current title has one.',
             f"Pin: call set_pinned for {who} with pinned=true."]
    return steps + [unpin_step(old)] if old and old != sid else steps


def stored(name: str) -> dict:
    """A state file in the OliverCode home, or {} when it is absent or unreadable."""
    try:
        found = json.loads((failure_log.home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def next_thread(project: str) -> int:
    """Take the next thread number for `project`, 1 to 10 and wrapping. Call it inside thread_state, so two threads never take one number."""
    counts = stored(THREAD_NUMBERS)
    last = counts.get(project)
    number = last % 10 + 1 if isinstance(last, int) else 1
    failure_log.write_private(failure_log.home() / THREAD_NUMBERS, json.dumps({**counts, project: number}, indent=2) + "\n")
    return number


@contextmanager
def thread_state():
    """thread-sessions.json for one writer at a time, saved on a clean exit with its newest KEEP_SESSIONS sessions."""
    path = failure_log.home() / THREAD_SESSIONS
    with failure_log.locked(path):
        found = stored(THREAD_SESSIONS)
        state = {key: found[key] if isinstance(found.get(key), dict) else {} for key in ("sessions", "pinned", "reserved")}
        yield state
        state["sessions"] = dict(list(state["sessions"].items())[-KEEP_SESSIONS:])
        failure_log.write_private(path, json.dumps(state, indent=2) + "\n")


def reserve_thread(project: str, writer: str) -> tuple[int, str]:
    """The number `write` gives the next thread, held until `read` so an overwritten handoff uses no second one, and the project's pinned session.
    The reservation names the sessions `write` takes the pin from, so `read` can tell one that took it later."""
    with thread_state() as state:
        number = state["reserved"].get(project, {}).get("number") or next_thread(project)
        old = state["pinned"].get(project, "")
        state["reserved"][project] = {"number": number, "unpinned": [writer, old]}
        return number, old


def reserved_steps(project: str, number: int, sid: str, old: str, unpinned: list[str]) -> list[str]:
    """For the thread that takes `write`'s number. `write`'s calls may never have been made, or its prompt was pasted into a chat by hand, so they are
    given again for a missing title or pin. A session that took the pin after `write` loses it either way."""
    later = bool(old) and old != sid and old not in unpinned
    return ([unpin_step(old)] if later else []) + [
        f'Thread: this one is "{project} {number}". If its title says so and it is pinned, no rename or pin step is needed. If either is missing, make these calls:',
        *name_steps(project, number, sid, "" if later else old)]


def claim_thread(project: str, sid: str, handoff: bool = False) -> tuple[int, list[str]]:
    """Number session `sid` once and record it as the project's pinned one. Returns its number and the title and pin lines for it, [] for a session that
    already holds a number. `handoff` takes the number `write` reserved."""
    with thread_state() as state:
        reserved = state["reserved"].pop(project, None) if handoff else None
        held = state["sessions"].get(sid, {}).get(project)
        if held:
            return held, []
        old = state["pinned"].get(project, "")
        number = reserved["number"] if reserved else next_thread(project)
        if sid:
            state["sessions"][sid] = {project: number}
            state["pinned"][project] = sid
    if reserved:
        return number, reserved_steps(project, number, sid, old, reserved["unpinned"])
    return number, name_steps(project, number, sid, old)


def command_errors(text: str) -> list[str]:
    """One 'line N: ...' for each drain or dispatch command in `text` that would print a usage error or name a repo that does not resolve."""
    errors = []
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        for name, tail in (FENCED_RE.findall(line) if fenced else COMMAND_RE.findall(line)):
            try:
                words = shlex.split(tail, comments=True)  # a trailing `# note` is not an argument
            except ValueError:
                words = tail.split()
            if words:
                words[-1] = words[-1].rstrip(".,;:)")
            if name == "dispatch":
                if words != ["--plan"] and cmd_dispatch._parse(words) is None:
                    errors.append(f"line {number}: `olivercode dispatch{tail.rstrip()}` is a usage error. {cmd_dispatch.USAGE}")
                continue
            repos, bad_flag, i = [], False, 0
            while i < len(words):
                if words[i] == "--parallel" and i + 1 < len(words) and words[i + 1].isdigit() and int(words[i + 1]) > 0:
                    i += 1
                elif words[i].startswith("-") and words[i] != "--foreground":
                    bad_flag = True
                elif not words[i].startswith("-"):
                    repos.append(words[i])
                i += 1
            if bad_flag or len(repos) != 1:
                errors.append(f"line {number}: `olivercode drain{tail.rstrip()}` is a usage error. {cmd_drain.USAGE}")
            elif cmd_drain.resolve_repo(repos[0]) is None:
                errors.append(f"line {number}: `olivercode drain{tail.rstrip()}` names {repos[0]}, which is not a repo with docs/backlog-config.json.")
    return errors


def drain_repo(text: str) -> str | None:
    """The repo named by the first `olivercode drain REPO` in `text` that resolves, or None. A handoff that names no drain gets no watch line (#1434)."""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        for name, tail in (FENCED_RE.findall(line) if fenced else COMMAND_RE.findall(line)):
            if name != "drain":
                continue
            try:
                words = shlex.split(tail, comments=True)  # a trailing `# note` is not an argument
            except ValueError:
                words = tail.split()
            repos = [w.rstrip(".,;:)") for i, w in enumerate(words) if not w.startswith("-") and not (i and words[i - 1] == "--parallel")]
            if repos and cmd_drain.resolve_repo(repos[0]) is not None:
                return repos[0]
    return None


def read_prompt(project: str, folder: Path) -> str:
    """The next thread's first prompt. It names this launcher by path, since the `olivercode` first on PATH can be another checkout."""
    launcher = shlex.quote(str(Path(__file__).resolve().parents[1] / "olivercode"))
    return f"Run {launcher} handoff read {shlex.quote(project)} in {folder} and continue from its Next steps. Use that launcher for every olivercode command."


def next_thread_steps(project: str, folder: Path) -> list[str]:
    """The calls the writing thread makes to start the next one in the desktop app, with its name and the pin."""
    number, old = reserve_thread(project, session())
    steps = [f"Start: call start_session with this prompt: {read_prompt(project, folder)}",
             f'Title: call set_session_title for the new session with "{project} {number}".',
             "Pin: call set_pinned for the new session with pinned=true.",
             unpin_step(session())]
    return steps + [unpin_step(old)] if old and old != session() else steps


def write(project: str, draft: Path, folder: Path) -> int:
    try:
        text = draft.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Refused: {draft} is not readable ({exc.strerror}).")
        return 1
    errors = command_errors(text)
    if errors:
        print(f"Refused: no handoff was written. {len(errors)} command(s) in {draft} would not run:")
        print("\n".join(errors))
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    keep = next((p for p in handoffs(project, folder) if p.resolve() == draft.resolve()), None)
    target = keep or folder / f"{project}-handoff-{time.strftime('%Y-%m-%d')}.md"
    if keep is None:
        shutil.move(str(draft), target)
    for old in handoffs(project, folder):
        if old.resolve() != target.resolve():
            old.unlink()
    print(f"Handoff written: {target}. It is the only {project} handoff.")
    print("\n".join(next_thread_steps(project, folder)))
    return 0


def read(project: str, folder: Path) -> int:
    found = handoffs(project, folder)
    if not found:
        print(f"No {project} handoff in {folder}.")
        return 1
    text = found[0].read_text(encoding="utf-8")
    number, steps = claim_thread(project, session(), handoff=True)  # before the delete, so a failed save leaves the handoff for the next read
    sys.stdout.write(text)
    for path in found:  # a second one is stale, so it goes too and one handoff is never left behind
        path.unlink()
    print(f"\nHandoff read and deleted: {found[0].name}. No copy is kept.")
    print("\n".join(steps) or f'Thread: this one is "{project} {number}", and no new name is needed.')
    repo = drain_repo(text)
    if repo:
        print(f"Watch: run `olivercode watch {repo} --until-exit` in the background, so this thread wakes only when the drain ends. Never use Monitor for it.")
    return 0


def command_handoff(argv: list[str]) -> int:
    folder = handoff_dir()
    if len(argv) == 3 and argv[0] == "write":
        return write(argv[1], Path(argv[2]).expanduser(), folder)
    if len(argv) == 2 and argv[0] == "read":
        return read(argv[1], folder)
    print(USAGE)
    return 1
