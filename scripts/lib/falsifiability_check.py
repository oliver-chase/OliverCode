"""Detect checks that cannot fail.

Ten defects in this repo turned out to be one shape: a check that reported success
it had not earned. Not sloppiness -- each was scaffolding that stayed after real
usage diverged, and none could be caught by reading the output, because the output
always said PASS.

  post-commit           printed "Verification: PASS", always exit 0
  Gate 4                announced "passed" over an empty pattern list
  Gate 2                silently passed everything when perl was absent
  CRITICAL_ISSUES       compared but never incremented -> exit 2 unreachable
  node --test *.mjs     exit 0 on zero matched files
  QA sections 1 and 7   printed findings-shaped output, never incremented
  apply-token-policy    filtered nothing for an unknown repo, said nothing
  findings_documented   accepted "" as a completed audit

The common property is unfalsifiability: no input could make them fail. This module
looks for that property directly, so the class stops recurring instead of being
rediscovered by hand.

Two detectors, both chosen because they are precise rather than clever -- a noisy
meta-check would be ignored, which is the very failure it exists to prevent.
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
