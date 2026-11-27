"""Launcher command `handoff`: one live handoff per project, deleted once the next thread has read it (#1321).

`olivercode handoff write PROJECT FILE` files FILE as PROJECT-handoff-DATE.md in the handoff folder and deletes the project's other handoffs.
`olivercode handoff read PROJECT` prints the handoff and deletes it, with no archive copy. Only regular files named PROJECT-handoff-*.md count, so
another project's handoffs and a folder that merely holds the word are left alone. Before write files anything it parses each `olivercode drain`
and `olivercode dispatch` command in FILE, without running one, and refuses a handoff whose command would print a usage error.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from lib import cmd_dispatch, cmd_drain

USAGE = "Usage: olivercode handoff write PROJECT FILE | olivercode handoff read PROJECT"
COMMAND_RE = re.compile(r"`olivercode\s+(drain|dispatch)\b([^`\n]*)`")  # a backticked command, never a sentence that names one
FENCED_RE = re.compile(r"\s*(?:\$\s*)?olivercode\s+(drain|dispatch)\b(.*)")  # a whole line inside a code fence


def handoff_dir() -> Path:
    return Path(os.environ.get("OLIVERCODE_HANDOFF_DIR") or Path.cwd()).expanduser()


def handoffs(project: str, folder: Path) -> list[Path]:
    """The project's handoff files in `folder`, newest first. A folder or a name for another project is not one."""
    pattern = re.compile(rf"{re.escape(project)}-handoff-.+\.md")
    found = [p for p in folder.glob("*.md") if p.is_file() and pattern.fullmatch(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


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
    return 0


def read(project: str, folder: Path) -> int:
    found = handoffs(project, folder)
    if not found:
        print(f"No {project} handoff in {folder}.")
        return 1
    sys.stdout.write(found[0].read_text(encoding="utf-8"))
    for path in found:  # a second one is stale, so it goes too and one handoff is never left behind
        path.unlink()
    print(f"\nHandoff read and deleted: {found[0].name}. No copy is kept.")
    return 0


def command_handoff(argv: list[str]) -> int:
    folder = handoff_dir()
    if len(argv) == 3 and argv[0] == "write":
        return write(argv[1], Path(argv[2]).expanduser(), folder)
    if len(argv) == 2 and argv[0] == "read":
        return read(argv[1], folder)
    print(USAGE)
    return 1
