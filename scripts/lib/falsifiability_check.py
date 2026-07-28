"""Detect checks that cannot fail.

Ten defects in this repo were one shape: a check that reported success it had not
earned. Each was scaffolding left behind after real usage diverged, and reading the
output could never catch any of them, because the output always said PASS.
FALSIFIABILITY-1 in docs/DECISIONS.md lists all ten.

Two detectors, precise rather than clever -- a noisy meta-check gets ignored, which
is the failure it exists to prevent.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# A counter compared against a threshold but never increased. This is exactly the
# CRITICAL_ISSUES bug: `X=0` ... `if [ "$X" -gt 0 ]` with no `X=$((X + 1))` anywhere,
# so the guarded branch is dead code.
_ASSIGN_ZERO = re.compile(r"^\s*(?:local\s+)?([A-Z_][A-Z0-9_]*)=0\s*$", re.MULTILINE)
_COMPARED = re.compile(r'\$\{?(\w+)\}?"?\s*(?:-gt|-ge|-ne)\s')
_INCREMENTED = re.compile(r"(\w+)=\$\(\(\s*\1\s*[+]|(\w+)\+\+|let\s+(\w+)")

# A script that talks about failing but has no way to exit nonzero.
_FAILURE_LANGUAGE = re.compile(r"\b(FAIL|BLOCKED|ERROR|failed|violation)\b")
_NONZERO_EXIT = re.compile(r"\bexit\s+[1-9]\b")

# Scripts whose contract is genuinely advisory: they inform, and something else
# decides. Each needs a reason, so the exemption list cannot quietly absorb a real bug.
ADVISORY_BY_CONTRACT = {
    # Reports per-repo hook state for a human; validate.sh treats it as advisory
    # because a fork with no fleet must still pass.
    "scripts/olivercode": "CLI: exit status is per-command, not a single check",
}


def _tracked_shell_scripts(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "*.sh", ".githooks/*"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return []
    return sorted({line for line in out.stdout.splitlines() if line.strip()})


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
        if rel in ADVISORY_BY_CONTRACT:
            continue
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
