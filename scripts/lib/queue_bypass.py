#!/usr/bin/env python3
"""The queue-bypass gate of validate.sh: no tracked script runs validation outside the one queued entry point (#757).

    queue_bypass.py [REPO_ROOT]

The entry point is `bash scripts/validate.sh`: its managed block takes a slot in the per-user validation queue before any gate
starts, so a builder, `olivercode land`, a hook, the nightly job all wait their turn there. Earlier queue stories
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
QUEUED = re.compile(r"validate[_-]queue|queue run|queued\(|OLIVERCODE_VALIDATE_SLOT|VALIDATE_QUEUE_SLOT")
SLOT_SKIP = re.compile(r"(VALIDATE_QUEUE_SLOT|OLIVERCODE_VALIDATE_SLOT|VALIDATE_QUEUE_BIN)=[^\s]*|env\s+-u\s+\S*(VALIDATE_QUEUE_SLOT|OLIVERCODE_VALIDATE_SLOT)")
SCRIPT_SUFFIXES = (".sh", ".py", ".bash", ".zsh")


def tracked(root: Path) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", "ls-files", "-z"], capture_output=True)
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
    for rel in tracked(root):
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
            elif (PY_SUITE if rel.endswith(".py") else SUITE).search(line) and not QUEUED.search(line):
                findings.append(f"{rel}:{n} starts the test suite directly, outside the validation queue. Use `{ENTRY}`, or wrap the command in `olivercode queue run --`")
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    findings = check(root)
    print("=== validate: checking that every caller goes through the validation queue ===")
    for f in findings:
        print(f"  [FAIL] {f}")
    if findings:
        print(f"=== validate: queue bypass check FAILED ({len(findings)} bypass(es)) ===")
        return 1
    print("=== validate: queue bypass check passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
