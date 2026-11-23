#!/usr/bin/env python3
"""The queue-bypass gate of validate.sh: no tracked script runs validation outside the one queued entry point (#757).

    queue_bypass.py [REPO_ROOT]

The entry point is `bash scripts/validate.sh`: its managed block takes a slot in the per-user validation queue before any gate
starts, so a builder, `olivercode land`, a hook, the nightly and conform all wait their turn there. Earlier queue stories
(#506, #519, #548, #572) were each undone by a script that started the test suite or a copy of validate.sh around the queue,
so this gate reads every tracked script and fails, naming the script and the entry point, when one of these holds:

  1. a tracked scripts/validate.sh lacks the managed queue block (it would run unqueued);
  2. a script starts the test suite directly (`python3 -m unittest`, `pytest`, `npm test`, `run-tests.sh`) on a line that
     does not go through the queue (`validate-queue run`, `queue run`, a call to validate_queue);
  3. a script starts validate.sh on a line that empties or replaces the queue variables (VALIDATE_QUEUE_SLOT,
     OLIVERCODE_VALIDATE_SLOT, VALIDATE_QUEUE_BIN), which skips the slot.

A repo's tests and docs may name these commands as text, so tests/, docs/, Markdown and test_*.py files are not read.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ENTRY = "bash scripts/validate.sh"
MARKER = "# managed:validate-queue"

# Files that are the entry point or the queue itself, which run inside a held slot or name the commands as data.
INSIDE = {"scripts/validate.sh", "scripts/lib/smoke_runner.py", "scripts/lib/queue_bypass.py", "scripts/lib/validate_queue.py",
          "scripts/lib/validate_gates.py", "scripts/hooks/queue_guard.py", "scripts/lib/cmd_repo.py", "scripts/lib/claude_settings.py",
          "core/templates/project/scripts/validate.sh"}

SUITE = re.compile(r"-m[ \t]+[\"']?(unittest|pytest)\b|(^|[\s\"'(;&|])pytest([\s\"')]|$)|\bnpm[ \t]+(run[ \t]+)?test\b|\brun-tests\.sh\b")
# In Python a start is a quoted command or an argv list, so a usage line in a docstring is not read as one.
PY_SUITE = re.compile(r"[\"']-m[\"']\s*,\s*[\"'](unittest|pytest)[\"']|[\"'](python3?\s+-m\s+(unittest|pytest)|pytest|npm\s+(run\s+)?test|bash\s+scripts/run-tests\.sh)\b")
# A line is queued when it runs the queue as a command or calls it, so a mention in a trailing comment, a string or an env value does not count.
QUEUED = re.compile(r"(^|[\s;&|(`])(\S*/)?(validate[_-]queue(\.py)?\s+run|olivercode\s+queue\s+run|queue\s+run)\b|[\"']{2}\s+run\b|\$\{?\w*queue\w*\}?\s+run\b|\bqueued\(|\bvalidate_queue\.(run|queued)\b")  # a quoted or variable path to the queue, such as python3 "$validate_queue" run, is blanked or unexpanded by _code
SLOT_SKIP = re.compile(r"(VALIDATE_QUEUE_SLOT|OLIVERCODE_VALIDATE_SLOT|VALIDATE_QUEUE_BIN)=[^\s]*|env\s+-u\s+\S*(VALIDATE_QUEUE_SLOT|OLIVERCODE_VALIDATE_SLOT)")
SCRIPT_SUFFIXES = (".sh", ".py", ".bash", ".zsh")


def _code(line: str) -> str:
    """The line with quoted strings blanked and any trailing comment cut, so a mention in either does not count as a queue call."""
    line = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", '""', line)
    return re.sub(r"\s#.*$", "", line)


class GitUnreadable(Exception):
    """git could not list the repo's tracked files."""


def tracked(root: Path) -> list[str]:
    try:
        done = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", "ls-files", "-z"], capture_output=True)
    except OSError as exc:
        raise GitUnreadable(f"git could not start ({exc})") from exc
    if done.returncode:
        raise GitUnreadable(f"git ls-files failed in {root}: {done.stderr.decode('utf-8', 'replace').strip()[:120] or 'no detail'}")
    return [f for f in done.stdout.decode("utf-8", "surrogateescape").split("\0") if f]


def _is_script(rel: str, text: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith(("tests/", "docs/")) or name.startswith("test_") or name.endswith(".md"):
        return False
    return rel.endswith(SCRIPT_SUFFIXES) or rel.startswith(".githooks/") or text.startswith("#!")


def logical_lines(text: str):
    """(first line number, text) per command, with a backslash continuation joined to the line it continues."""
    start, parts = 0, []
    for n, line in enumerate(text.splitlines(), 1):
        if not parts:
            start = n
        if line.rstrip().endswith("\\"):
            parts.append(line.rstrip()[:-1])
            continue
        parts.append(line)
        yield start, " ".join(parts)
        parts = []
    if parts:
        yield start, " ".join(parts)


def check(root: Path) -> list[str]:
    """One finding per bypass, each naming the script, the line and the entry point to use."""
    root = Path(root)
    findings = []
    for rel in tracked(root):  # raises GitUnreadable when git cannot list the files
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if rel.endswith("scripts/validate.sh") and MARKER not in text:
            findings.append(f"{rel} has no queue block, so it runs unqueued. Add the managed block from core/templates/project/scripts/validate-queue.snippet.sh")
        if rel in INSIDE or not _is_script(rel, text):
            continue
        for n, line in logical_lines(text):
            if line.strip().startswith("#"):
                continue
            if "validate.sh" in line and SLOT_SKIP.search(line):
                findings.append(f"{rel}:{n} starts validate.sh with the queue variables replaced, which skips its slot. Use `{ENTRY}` as it is")
            elif (PY_SUITE if rel.endswith(".py") else SUITE).search(line) and not QUEUED.search(_code(line)):
                findings.append(f"{rel}:{n} starts the test suite directly, outside the validation queue. Use `{ENTRY}`, or wrap the command in `olivercode queue run --`")
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    print("=== validate: checking that every caller goes through the validation queue ===")
    try:
        findings = check(root)
    except GitUnreadable as exc:
        print(f"  [FAIL] unknown: {exc}, so no script was read")
        print("=== validate: queue bypass check FAILED (the tracked files could not be read) ===")
        return 1
    for f in findings:
        print(f"  [FAIL] {f}")
    if findings:
        print(f"=== validate: queue bypass check FAILED ({len(findings)} bypass(es)) ===")
        return 1
    print("=== validate: queue bypass check passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
