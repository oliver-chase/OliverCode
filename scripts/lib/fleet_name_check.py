"""Tracked files must not name another fleet repo.

The owner's other repo names are the git checkouts directly under repoRoot and the names in `privateRepos` in
olivercode.local.json, both private to the machine. A tracked line that names one of them leaks the operator's
other projects into the public repo. The check fails on each tracked line that names one, with the file and line.
A machine with no other checkout and no private repo, such as a fork's, has no names to find and passes.
"""

from __future__ import annotations

import re
from pathlib import Path

from lib.gitfiles import tracked_files
from lib import placement
from lib.local_config import private_repos

# The framework's own name is in every path and every doc, so it is never a fleet name to find.
OWN_NAMES = frozenset({"olivercode"})
# A bare word such as "docs" or "site" is ordinary text, so a name counts only in its owner/name form.
# Gate sources every fleet repo tracks a built copy of, so an edit here forces a commit in each repo.
# Their example names are cleared at the next fleet-wide hook sync (#665), and this list empties then.
SYNCED_GATES = frozenset({"core/hooks/gates/owner-identifiers.sh", ".githooks/pre-commit"})


def fleet_names() -> list[str]:
    """The lowercased names of the git checkouts directly under repoRoot and of the private repos, longest first."""
    try:
        found = {d.name.lower() for d in placement.config().root.iterdir() if (d / ".git").is_dir()}  # a linked worktree's .git is a file
    except OSError:
        found = set()  # no repoRoot folder, so only the private repos are named, and validation must not crash
    names = found | {name.lower() for name in private_repos()}
    return sorted(names - OWN_NAMES, key=lambda n: (-len(n), n))


def check_all(repo_root: Path) -> list[str]:
    names = fleet_names()
    if not names:
        return []
    alternatives = "|".join(re.escape(n) for n in names)
    # owner/name standing alone, or after a host (github.com/owner/name/issues/3), where a deeper path still names the repo.
    # A bare path such as docs/site/index.md or lib/site.py has no host, so it never matches; only a .git suffix may follow the name.
    pattern = re.compile(r"(?<![A-Za-z0-9._-])[A-Za-z0-9][A-Za-z0-9._-]*/(?:" + alternatives + r")(?:\.git(?![A-Za-z0-9]))?(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])"
                         r"|[A-Za-z0-9-]\.[A-Za-z]{2,}[/:][A-Za-z0-9][A-Za-z0-9._-]*/(?:" + alternatives + r")(?![A-Za-z0-9_-])",
                         re.IGNORECASE)
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
                    f"{rel}:{number} names another fleet repo; "
                    "use a generic name or move the file out of the tracked tree"
                )
    return failures
