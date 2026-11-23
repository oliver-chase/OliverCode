"""Tracked files must not name another fleet repo.

The fleet's repo names live in the local registry, which is private and never tracked. A tracked
line that names one of them leaks the operator's other projects into the public repo. The check reads
the names from the registry this checkout uses, then fails on each tracked line that names one, with
the file and line. A checkout whose registry is empty, such as a fork, has no names to find and passes.
"""

from __future__ import annotations

import re
from pathlib import Path

from lib.gitfiles import tracked_files
from lib.repo_profiles import load_repo_profiles

# The framework's own name is in every path and every doc, so it is never a fleet name to find.
OWN_NAMES = frozenset({"olivercode"})
# A short name matches inside ordinary words, so only names this long or longer are checked.
MIN_LENGTH = 4
# Gate sources every fleet repo tracks a built copy of, so an edit here forces a commit in each repo.
# Their example names are cleared at the next fleet-wide hook sync (#665), and this list empties then.
SYNCED_GATES = frozenset({"core/hooks/gates/owner-identifiers.sh", ".githooks/pre-commit"})


def fleet_names(repo_root: Path) -> list[str]:
    """The lowercased fleet repo names in this checkout's registry, longest first."""
    try:
        profiles, _source = load_repo_profiles(repo_root)
    except (OSError, ValueError):
        # A fork with no registry, or a damaged one, has no names to find, and the check must not crash validation.
        return []
    names = {name.lower() for name in profiles if len(name) >= MIN_LENGTH}
    return sorted(names - OWN_NAMES, key=lambda n: (-len(n), n))


def check_all(repo_root: Path) -> list[str]:
    names = fleet_names(repo_root)
    if not names:
        return []
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])", re.IGNORECASE)
    failures = []
    for rel in tracked_files(repo_root):
        if str(rel) in SYNCED_GATES:
            continue
        try:
            text = (Path(repo_root) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = pattern.search(line)
            if match:
                failures.append(
                    f"{rel}:{number} names another fleet repo ({match.group(1).lower()}); "
                    "use a generic name or move the file out of the tracked tree"
                )
    return failures
