"""Doc-vs-code consistency checks.

One failure class: a tracked doc asserts something the code contradicts. Collapsed
into a single checker per FRAMEWORK_BASELINE.md's removal rule (a validator that
duplicates another's failure class gets merged, not added alongside).

Checks:
  1. skills/INDEX.md's table matches the skills/*/SKILL.md directories, both ways,
     and each SKILL.md's frontmatter `name:` matches its directory name. The launcher
     reads frontmatter while humans read the table; they can drift apart silently.
  2. No tracked doc claims a pre-commit gate count that contradicts the hook itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

INDEX_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|", re.MULTILINE)
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
GATE_DECL = re.compile(r"Gate (\d+)/(\d+)")
# "8 gates", "the 8 gates of", "-- 6 gates:" etc. Bare "N gates" is the claim shape.
# Word forms are matched too: prose drifts to "the six gates" and a digits-only pattern
# would pass it silently, which is the exact class this checker exists to stop.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
GATE_CLAIM = re.compile(
    r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+gates\b", re.IGNORECASE
)


def _claimed_count(token: str) -> int | None:
    """Normalize a digit or number-word to an int; None if neither."""
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


def _tracked(repo_root: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def check_skill_index(repo_root: Path) -> list[str]:
    failures: list[str] = []
    skills_dir = repo_root / "skills"
    index_path = skills_dir / "INDEX.md"
    if not index_path.is_file():
        return ["  [SKILLS] skills/INDEX.md is missing"]

    on_disk = {
        p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    }
    in_index = set(INDEX_ROW.findall(index_path.read_text(encoding="utf-8")))

    for name in sorted(in_index - on_disk):
        failures.append(
            f"  [SKILLS] INDEX.md lists `{name}` but skills/{name}/SKILL.md does not exist"
        )
    for name in sorted(on_disk - in_index):
        failures.append(
            f"  [SKILLS] skills/{name}/SKILL.md exists but INDEX.md has no row for it"
        )

    for name in sorted(on_disk):
        text = (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
        match = FRONTMATTER_NAME.search(text)
        if not match:
            failures.append(f"  [SKILLS] skills/{name}/SKILL.md has no frontmatter name:")
            continue
        declared = match.group(1).strip().strip("\"'")
        if declared != name:
            failures.append(
                f"  [SKILLS] skills/{name}/SKILL.md declares name: {declared} "
                f"(the launcher lists it under that name, the index under {name})"
            )
    return failures


def check_gate_count(repo_root: Path) -> list[str]:
    """The hook is the source of truth for how many gates there are."""
    hook = repo_root / ".githooks" / "pre-commit"
    if not hook.is_file():
        return ["  [GATES] .githooks/pre-commit is missing"]

    totals = {int(total) for _, total in GATE_DECL.findall(hook.read_text(encoding="utf-8"))}
    if not totals:
        return ["  [GATES] .githooks/pre-commit declares no 'Gate N/M' banners to count"]
    if len(totals) > 1:
        return [
            f"  [GATES] .githooks/pre-commit is internally inconsistent: "
            f"banners claim totals {sorted(totals)}"
        ]
    actual = totals.pop()

    failures: list[str] = []
    for rel in _tracked(repo_root, "*.md"):
        if rel.startswith("core/templates/"):
            continue  # the template hook has its own, smaller gate count
        for line in (repo_root / rel).read_text(encoding="utf-8").splitlines():
            for token in GATE_CLAIM.findall(line):
                claimed = _claimed_count(token)
                if claimed is not None and claimed != actual:
                    failures.append(
                        f"  [GATES] {rel} claims {token} gates; "
                        f".githooks/pre-commit has {actual}"
                    )
    return failures


def check_gate_integrity(repo_root: Path) -> list[str]:
    """The hook must actually contain as many gates as its banners claim.

    Replaces the only unique check the post-commit hook performed (grep for "Gate 6
    still present"). That hook could not block, always exited 0, and its skill-count
    check globbed a path that had not existed for months without anyone noticing --
    so it was not being read. This runs in validate.sh and fails closed.

    Counts DISTINCT gate numbers, not echo sites: gates 7 and 8 each print from two
    branches (ran / skipped), so a naive line count reports more gates than exist.
    """
    hook = repo_root / ".githooks" / "pre-commit"
    if not hook.is_file():
        return ["  [GATES] .githooks/pre-commit is missing"]

    declared = GATE_DECL.findall(hook.read_text(encoding="utf-8"))
    if not declared:
        return ["  [GATES] .githooks/pre-commit declares no 'Gate N/M' banners"]

    totals = {int(total) for _, total in declared}
    if len(totals) > 1:
        return [f"  [GATES] hook banners disagree on the total: {sorted(totals)}"]
    claimed = totals.pop()
    present = {int(num) for num, _ in declared}

    failures = []
    if len(present) != claimed:
        missing = sorted(set(range(1, claimed + 1)) - present)
        failures.append(
            f"  [GATES] hook claims {claimed} gates but only {len(present)} are present"
            + (f"; missing gate number(s): {missing}" if missing else "")
        )
    return failures


def check_all(repo_root: Path) -> list[str]:
    return (
        check_skill_index(repo_root)
        + check_gate_count(repo_root)
        + check_gate_integrity(repo_root)
    )
