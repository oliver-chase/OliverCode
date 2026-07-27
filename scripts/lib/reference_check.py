"""Backtick repo-path reference integrity.

The markdown-link half of link-check.sh only sees inline `[text](path.md)` links.
This repo's real cross-references are backtick-quoted repo paths, and there are two
orders of magnitude more of them — every stale path the full-file audit found lived
in a backtick, invisible to a link checker that only reads markdown link syntax.

A "reference" here is a backtick-quoted token whose first path segment is a tracked
top-level directory. Anything else (prose, commands, identifiers) is ignored.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

BACKTICK = re.compile(r"`([^`\n]+)`")

# First path segment must be one of these for a token to be treated as a repo path.
TRACKED_ROOTS = (
    "scripts/",
    "core/",
    "docs/",
    "shared/",
    "skills/",
    "tests/",
    ".githooks/",
    ".github/",
    ".claude-optimization/",
)

# Placeholder syntax — the token names a shape, not a file that exists.
PLACEHOLDER_CHARS = set("<>*|$")

# Paths that are correct as written but resolve inside a DOWNSTREAM repo, not this
# one. A contract that tells another repo where to put its files necessarily names
# paths absent here; flagging them would make the contract unwritable.
DOWNSTREAM_RELATIVE = frozenset(
    {
        "docs/repo-structure-contract.md",
        "docs/SETUP_MODES.md",
        "docs/MANUAL_SETUP.md",
        # OliverCode keeps its own at the repo root; `docs/ARCHITECTURE.md` only ever
        # names a downstream repo's copy (e.g. in docs/ADOPTING.md's rewrite template).
        "docs/ARCHITECTURE.md",
        "scripts/validate-repo.sh",
        "scripts/bootstrap-profile.sh",
        "scripts/run-profile-checks.sh",
        "scripts/check-structure-contract.mjs",
        "scripts/check-planning-doc-governance.py",
        "scripts/install-planning-governance-hook.sh",
        "scripts/oc-supabase-keepalive.sh",
        ".github/user-stories/",
        ".github/user-stories/README.md",
        ".github/user-stories/_index.md",
        ".githooks/pre-commit-private",
        "supabase/keepalive.sql",
    }
)

# Files whose whole job is to name wrong locations. Their paths must NOT resolve.
ANTI_PATTERN_FILES = frozenset({"core/contracts/FILE_LOCATION_STANDARD.md"})

# Everything under here describes the repo a template is stamped INTO.
TEMPLATE_PREFIX = "core/templates/"

# Gitignored local layers. Documenting them is correct, and a fresh clone lacks them --
# these must stay exempt or `validate.sh` fails for everyone who forks this repo
# (verified against a clean clone: memory/ and state/ are created per user, never tracked).
OPTIONAL_PREFIXES = (
    "runtime/control-plane/",
    "runtime/manifests",
    "local/",
    ".claude-optimization/memory/",
    ".claude-optimization/state/",
)


def _tracked_files(repo_root: Path) -> list[str]:
    """Tracked files PLUS untracked-but-not-ignored ones.

    `--others --exclude-standard` matters: a brand-new file is untracked until the
    commit that adds it, so a tracked-only listing cannot see broken references in
    the very change being made. Caught for real -- a new doc's dangling ref passed
    validate.sh while the file was untracked and only failed after it was committed,
    which is exactly backwards for a pre-commit gate.
    """
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return []
    return sorted({line for line in out.stdout.splitlines() if line.strip()})


def _is_exempt(token: str) -> bool:
    if any(c in token for c in PLACEHOLDER_CHARS):
        return True
    if token in DOWNSTREAM_RELATIVE:
        return True
    if token.startswith(OPTIONAL_PREFIXES):
        return True
    return False


def _candidates(text: str) -> list[str]:
    found = []
    for raw in BACKTICK.findall(text):
        token = raw.strip().split()[0] if raw.strip() else ""
        token = token.rstrip(".,;:)").split("(")[0]
        if token.startswith(TRACKED_ROOTS):
            found.append(token)
    return found


def check_references(repo_root: Path) -> tuple[int, list[str]]:
    """Return (checked_count, [failure lines]).

    A reference fails when it names a path under a tracked root that does not exist
    on disk and is not exempt. Directory references (trailing slash) are checked as
    directories; everything else must be a file or a directory.
    """
    failures: list[str] = []
    checked = 0

    for rel in _tracked_files(repo_root):
        if rel.startswith(TEMPLATE_PREFIX) or rel in ANTI_PATTERN_FILES:
            continue
        if not rel.endswith((".md", ".json", ".sh", ".py", ".yml", ".yaml", ".mjs")):
            continue
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token in _candidates(text):
            if _is_exempt(token):
                continue
            checked += 1
            if not (repo_root / token).exists():
                failures.append(f"  [BROKEN REF] {rel} -> `{token}` (not found on disk)")

    return checked, failures
