"""Launcher command `handoff`: one live handoff per project, deleted once the next thread has read it (#1321).

`olivercode handoff write PROJECT FILE` files FILE as PROJECT-handoff-DATE.md in the handoff folder and deletes the project's other handoffs.
`olivercode handoff read PROJECT` prints the handoff and deletes it, with no archive copy, then names the reading thread "PROJECT N", N from 1 to 10 (#1353). Only regular files named PROJECT-handoff-*.md count, so
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
from pathlib import Path

from lib import cmd_dispatch, cmd_drain, cmd_owner, failure_log

USAGE = "Usage: olivercode handoff write PROJECT FILE | olivercode handoff read PROJECT"
COMMAND_RE = re.compile(r"`olivercode\s+(drain|dispatch)\b([^`\n]*)`")  # a backticked command, never a sentence that names one
FENCED_RE = re.compile(r"\s*(?:\$\s*)?olivercode\s+(drain|dispatch)\b(.*)")  # a whole line inside a code fence
THREAD_NUMBERS = "thread-numbers.json"  # project -> last thread number, in the OliverCode home, never in the handoff folder


def handoff_dir() -> Path:
    return Path(os.environ.get("OLIVERCODE_HANDOFF_DIR") or Path.cwd()).expanduser()


def handoffs(project: str, folder: Path) -> list[Path]:
    """The project's handoff files in `folder`, newest first. A folder or a name for another project is not one."""
    pattern = re.compile(rf"{re.escape(project)}-handoff-.+\.md")
    found = [p for p in folder.glob("*.md") if p.is_file() and pattern.fullmatch(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def session() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def unpin_step() -> str:
    """The pin call for the thread that wrote the handoff. An open owner-queue item that names it keeps its pin."""
    if session() and any(i["session"] == session() for i in cmd_owner.open_items()):
        return "Pin: leave it pinned, since an open owner-queue item names this session."
    if not session():
        return "Pin: call set_pinned for this session with pinned=false, unless `olivercode owner list` shows an open item for this session."
    return f"Pin: call set_pinned for {session()} with pinned=false."


def next_thread(project: str) -> int:
    """The next thread number for `project`, 1 to 10 and wrapping. Stored only when a handoff is read, so an overwritten one uses no number."""
    path = failure_log.home() / THREAD_NUMBERS
    try:
        counts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        counts = {}
    if not isinstance(counts, dict):
        counts = {}
    last = counts.get(project)
    number = last % 10 + 1 if isinstance(last, int) else 1
    failure_log.write_atomic(path, json.dumps({**counts, project: number}, indent=2) + "\n")
    return number


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
                words = shlex.split(tail)
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
    print(unpin_step())
    return 0


def read(project: str, folder: Path) -> int:
    found = handoffs(project, folder)
    if not found:
        print(f"No {project} handoff in {folder}.")
        return 1
    text = found[0].read_text(encoding="utf-8")
    name = f"{project} {next_thread(project)}"  # numbered before the delete, so a failed save leaves the handoff for the next read
    sys.stdout.write(text)
    for path in found:  # a second one is stale, so it goes too and one handoff is never left behind
        path.unlink()
    print(f"\nHandoff read and deleted: {found[0].name}. No copy is kept.")
    print(f'Title: call set_session_title for {session() or "this session"} with "{name}", keeping an "{cmd_owner.OWNER_PREFIX}" prefix in front if its current title has one.')
    return 0


def command_handoff(argv: list[str]) -> int:
    folder = handoff_dir()
    if len(argv) == 3 and argv[0] == "write":
        return write(argv[1], Path(argv[2]).expanduser(), folder)
    if len(argv) == 2 and argv[0] == "read":
        return read(argv[1], folder)
    print(USAGE)
    return 1
