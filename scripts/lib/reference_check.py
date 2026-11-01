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
    "runtime/",
)

# `$OC/...` is how CLAUDE.md names a path inside this repo from any working directory, so it
# is a real reference once the prefix comes off. Any other `$` still marks a placeholder.
OC_PREFIX = "$OC/"

# Placeholder syntax — the token names a shape, not a file that exists.
PLACEHOLDER_CHARS = set("<>*|$")

# Paths that are correct as written but resolve inside a DOWNSTREAM repo, not this
# one. A contract that tells another repo where to put its files necessarily names
# paths absent here; flagging them would make the contract unwritable.
DOWNSTREAM_RELATIVE = frozenset(
    {
        "docs/repo-structure-contract.md",
        "scripts/validate-repo.sh",
        "scripts/bootstrap-profile.sh",
        "scripts/run-profile-checks.sh",
        "scripts/check-structure-contract.mjs",
        "scripts/check-planning-doc-governance.py",
        "scripts/check-backlog-hygiene.mjs",
        ".githooks/pre-commit-private",
    }
)

# Everything under here describes the repo a template is stamped INTO.
TEMPLATE_PREFIX = "core/templates/"

# A plan's whole job is describing paths that don't exist yet (what Step N will build)
# or that exist in a different repo the plan is centered on (the vault, a fleet repo) --
# neither case is a real claim about this repo's current tree. Added 2026-09-15 after a
# plan doc correctly describing a not-yet-built scripts/local-scheduler/ failed this
# check the same way a real broken reference would, with no way to tell the two apart.
PLANS_PREFIX = "docs/plans/"

# A skill's own tests build fake skills in a temporary folder and name paths inside them,
# so their paths describe that fixture, never this repo's tree.
SKILL_TEST = re.compile(r"^skills/[^/]+/scripts/test_[^/]+\.py$")

# Gitignored local layers. Documenting them is correct, and a fresh clone lacks them --
# these must stay exempt or `validate.sh` fails for everyone who forks this repo
# (verified against a clean clone: memory/ and state/ are created per user, never tracked).
OPTIONAL_PREFIXES = (
    "runtime/control-plane/",
    "runtime/manifests",
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
        if token.startswith(OC_PREFIX):
            token = token[len(OC_PREFIX):]
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
        if rel.startswith(TEMPLATE_PREFIX) or rel.startswith(PLANS_PREFIX) or SKILL_TEST.match(rel):
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
            # pathlib drops a trailing slash, so `exists()` alone let a file pass as a directory.
            target = repo_root / token
            if not (target.is_dir() if token.endswith("/") else target.exists()):
                failures.append(f"  [BROKEN REF] {rel} -> `{token}` (not found on disk)")

    return checked, failures
