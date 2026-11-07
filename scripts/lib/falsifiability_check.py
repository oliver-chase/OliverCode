"""Detect checks that cannot fail.

A check that reports success it has not earned is the defect this module looks for.
Reading the output cannot catch it, because the output always says PASS.
GATE-FALSIFIABILITY-1 in docs/DECISIONS.md lists the known cases.

Two detectors, kept precise because a noisy meta-check gets ignored, which is the
failure it exists to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

from lib.gitfiles import tracked_files

# A counter compared against a threshold but never increased. This is exactly the
# CRITICAL_ISSUES bug: `X=0` ... `if [ "$X" -gt 0 ]` with no `X=$((X + 1))` anywhere,
# so the guarded branch is dead code.
_ASSIGN_ZERO = re.compile(r"^\s*(?:local\s+)?([A-Z_][A-Z0-9_]*)=0\s*$", re.MULTILINE)
_COMPARED = re.compile(r'\$\{?(\w+)\}?"?\s*(?:-gt|-ge|-ne)\s')
_INCREMENTED = re.compile(r"(\w+)=\$\(\(\s*\1\s*[+]|(\w+)\+\+|let\s+(\w+)")

# A script that talks about failing but has no way to exit nonzero.
_FAILURE_LANGUAGE = re.compile(r"\b(FAIL|BLOCKED|ERROR|failed|violation)\b")
_NONZERO_EXIT = re.compile(r"\bexit\s+[1-9]\b")

def _tracked_shell_scripts(repo_root: Path) -> list[str]:
    return sorted(set(tracked_files(repo_root, "*.sh", ".githooks/*")))


def check_dead_counters(repo_root: Path) -> list[str]:
    """Find counters that are compared but never incremented."""
    failures: list[str] = []
    for rel in _tracked_shell_scripts(repo_root):
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        assigned = set(_ASSIGN_ZERO.findall(text))
        if not assigned:
            continue
        compared = set(_COMPARED.findall(text))
        incremented = {g for match in _INCREMENTED.findall(text) for g in match if g}
        for name in sorted(assigned & compared):
            if name not in incremented:
                failures.append(
                    f"  [UNFALSIFIABLE] {rel}: '{name}' is set to 0 and compared, but never "
                    f"incremented — the branch it guards can never run"
                )
    return failures


def check_scripts_can_fail(repo_root: Path) -> list[str]:
    """Find scripts that report failure states but cannot exit nonzero."""
    failures: list[str] = []
    for rel in _tracked_shell_scripts(repo_root):
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Strip comments: a script may discuss failure without implementing it.
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        if _FAILURE_LANGUAGE.search(code) and not _NONZERO_EXIT.search(code):
            failures.append(
                f"  [UNFALSIFIABLE] {rel}: reports failure states but has no nonzero exit — "
                f"nothing can act on what it finds"
            )
    return failures


def check_all(repo_root: Path) -> list[str]:
    return check_dead_counters(repo_root) + check_scripts_can_fail(repo_root)
