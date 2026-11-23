"""An OliverCode clone is engine only: personal files are refused at commit and flagged by conform.

A personal file is one that belongs to a single owner: this machine's config, a filled-in fleet registry,
local memory, a story or queue item, or any file whose path or text names a repo in the owner's fleet. All of
those live in the private olivercode-fleet repo. The commit gate runs this module through docs/SUITE-CHECKS.json
on the staged files, and `olivercode conform` runs it on the whole checkout.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

from lib.fleet_name_check import SYNCED_GATES, fleet_names
from lib.local_config import FLEET_NAME

FLEET_REPO = FLEET_NAME
# Paths that only ever hold one owner's data.
PERSONAL_GLOBS = (
    "olivercode.local.json", "*.local.json", "docs/LESSONS.jsonl", ".claude-optimization/memory/*",
    ".claude-optimization/state/*", "stories/*", "docs/stories/*", "queue/*", "owner-queue/*", "docs/owner-queue/*",
)
FIX = f"move it to the private {FLEET_REPO} repo and keep it out of this checkout"


def _read(root: Path, rel: str, staged: bool) -> str:
    if staged:
        done = subprocess.run(["git", "-C", str(root), "show", f":{rel}"], capture_output=True, text=True, check=False)
        return done.stdout if done.returncode == 0 else ""
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _filled_registry(text: str) -> bool:
    try:
        return bool(json.loads(text).get("profiles"))
    except (ValueError, AttributeError):
        return False


def personal_findings(root: Path, paths: list[str], staged: bool = False) -> list[str]:
    """One line per personal file among PATHS: the file, why it is personal and the fix."""
    names = fleet_names(root)
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])", re.IGNORECASE) if names else None
    found = []
    for rel in paths:
        if rel.startswith(".secrets/") and rel != ".secrets/README.md":
            found.append(f"{rel} is a secret: unstage it and keep it out of git")
            continue
        if any(fnmatch.fnmatch(rel, g) for g in PERSONAL_GLOBS) and not rel.endswith(".example.json"):
            why = "personal to one owner"
        elif rel == "shared/repo-profiles.json" and _filled_registry(_read(root, rel, staged)):
            why = "a filled-in fleet registry"
        elif pattern and rel not in SYNCED_GATES and (hit := pattern.search(rel) or pattern.search(_read(root, rel, staged))):
            why = "names a fleet repo"
        else:
            continue
        found.append(f"{rel} is {why}: {FIX}")
    return found


def staged_paths(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, check=False)
    return [line for line in out.stdout.splitlines() if line]


def checkout_paths(root: Path) -> list[str]:
    """Tracked files plus untracked files git does not ignore: the files that could reach a commit."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True, check=False)
    return sorted({line for line in out.stdout.splitlines() if line and (root / line).is_file()})


def main(argv: list[str]) -> int:
    """The commit gate: refuse the staged files named in ARGV (all staged files when none) that are personal."""
    root = Path.cwd()
    found = personal_findings(root, argv or staged_paths(root), staged=True)
    for line in found:
        print(f"BLOCKED: {line}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
