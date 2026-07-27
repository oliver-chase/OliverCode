"""Doc-vs-code consistency checks.

One failure class: a tracked doc asserts something the code contradicts. Collapsed
into a single checker per FRAMEWORK_BASELINE.md's removal rule (a validator that
duplicates another's failure class gets merged, not added alongside).

Checks:
  1. skills/INDEX.md's table matches the skills/*/SKILL.md directories, both ways,
     and each SKILL.md's frontmatter `name:` matches its directory name. The launcher
     reads frontmatter while humans read the table; they can drift apart silently.
  2. No tracked doc claims a pre-commit gate count that contradicts the hook it is
     about. Coverage is per-repo-type -- 8 gates in OliverCode, 6 in an adopted repo,
     2 in the private variant -- so a claim is resolved to its hook before comparing.
  3. Every hook variant is internally consistent, and docs/governance.md's coverage
     table (the single home for those counts) matches all three.
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
# Up to three modifier words may sit between the number and "gates". Without this the
# pattern missed README's own headline claim -- "8 pre-commit gates" -- because the
# number was not adjacent to the noun. Modifiers must be alphabetic, so "6 of the 8
# gates" still binds to the 8 rather than reading the 6 as a total.
GATE_CLAIM = re.compile(
    r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+(?:[a-z][a-z-]*\s+){0,3}gates\b",
    re.IGNORECASE,
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


# Every hook variant, and how a doc line signals which one it is talking about.
# Gate coverage is NOT uniform: OliverCode runs 8 on itself, an adopted repo 6, the
# vault's private variant 2. docs/governance.md holds the human table.
HOOKS = {
    "olivercode": Path(".githooks/pre-commit"),
    "template": Path("core/templates/project/pre-commit"),
    "template-private": Path("core/templates/project/pre-commit-private"),
}
# Checked most-specific first: "private" wins over a bare mention of "template".
_HOOK_CUES = (
    ("template-private", ("private variant", "pre-commit-private", "private template")),
    ("template", ("template", "adopted repo", "fleet repo", "product repo",
                  "downstream", "core/templates", "project repo")),
)


def _hook_totals(repo_root: Path) -> tuple[dict[str, int], list[str]]:
    """Real gate total per hook variant, read from the hooks themselves."""
    totals: dict[str, int] = {}
    problems: list[str] = []
    for name, rel in HOOKS.items():
        path = repo_root / rel
        if not path.is_file():
            if name == "olivercode":
                problems.append(f"  [GATES] {rel} is missing")
            continue  # a fork need not ship every variant
        declared = {int(t) for _, t in GATE_DECL.findall(path.read_text(encoding="utf-8"))}
        if not declared:
            problems.append(f"  [GATES] {rel} declares no 'Gate N/M' banners to count")
        elif len(declared) > 1:
            problems.append(
                f"  [GATES] {rel} is internally inconsistent: banners claim totals "
                f"{sorted(declared)}. Every banner in one hook must print the same total."
            )
        else:
            totals[name] = declared.pop()
    return totals, problems


def _hook_for_line(rel: str, line: str) -> str:
    """Which hook a gate-count claim refers to, from the doc path and the line's wording."""
    haystack = f"{rel} {line}".lower()
    for hook, cues in _HOOK_CUES:
        if any(cue in haystack for cue in cues):
            return hook
    return "olivercode"


def check_gate_count(repo_root: Path) -> list[str]:
    """No tracked doc may claim a gate count the corresponding hook contradicts.

    Resolves each claim to the hook it is ABOUT, rather than comparing everything to
    OliverCode's own hook. That earlier shortcut is why this check passed for months
    while five documents told forkers their repos would get eight gates: the docs said
    "8", OliverCode's hook had 8, and the template's 6 was never consulted -- the old
    body skipped core/templates/ outright with the comment "the template hook has its
    own, smaller gate count". The discrepancy was known to the checker and unchecked.
    """
    totals, failures = _hook_totals(repo_root)
    if not totals:
        return failures

    for rel in _tracked(repo_root, "*.md"):
        for line in (repo_root / rel).read_text(encoding="utf-8").splitlines():
            for token in GATE_CLAIM.findall(line):
                claimed = _claimed_count(token)
                if claimed is None:
                    continue
                hook = _hook_for_line(rel, line)
                actual = totals.get(hook)
                if actual is not None and claimed != actual:
                    failures.append(
                        f"  [GATES] {rel} claims {token} gates for the {hook} hook, which "
                        f"has {actual}. If the claim is about a different hook, name it on "
                        f"the same line (\"adopted repo\", \"private variant\"); the cue list "
                        f"is _HOOK_CUES in scripts/lib/consistency_check.py."
                    )
    return failures


def check_gate_coverage_table(repo_root: Path) -> list[str]:
    """docs/governance.md's per-repo Total row must match the real hooks.

    That table is the single home for gate coverage and every other doc points at it,
    so a stale row propagates everywhere by design.
    """
    doc = repo_root / "docs" / "governance.md"
    if not doc.is_file():
        return ["  [GATES] docs/governance.md is missing — it holds the gate coverage table"]

    row = next(
        (l for l in doc.read_text(encoding="utf-8").splitlines()
         if l.lstrip().startswith("| **Total**")),
        None,
    )
    if row is None:
        return [
            "  [GATES] docs/governance.md has no '| **Total** |' row in its gate coverage "
            "table — that row is what pins the per-repo counts to the hooks"
        ]

    stated = [int(n) for n in re.findall(r"\*\*(\d+)\*\*", row)]
    totals, failures = _hook_totals(repo_root)
    expected = [totals.get(h) for h in ("olivercode", "template", "template-private")]
    expected = [e for e in expected if e is not None]
    if stated != expected:
        failures.append(
            f"  [GATES] docs/governance.md's coverage table totals {stated} but the hooks "
            f"have {expected} (OliverCode, adopted repo, private variant)"
        )
    return failures


def check_gate_integrity(repo_root: Path) -> list[str]:
    """Every hook must actually contain as many gates as its banners claim.

    Replaces the only unique check the post-commit hook performed (grep for "Gate 6
    still present"). That hook could not block, always exited 0, and its skill-count
    check globbed a path that had not existed for months without anyone noticing --
    so it was not being read. This runs in validate.sh and fails closed.

    Runs over ALL hook variants, not just OliverCode's. Checking only OliverCode's was
    a real blind spot: the public template printed "Gate 1/5" through "Gate 5/5" and
    then "Gate 6/6", so it disagreed with itself about its own size and no check looked.

    Counts DISTINCT gate numbers, not echo sites: a conditional gate prints from two
    branches (ran / skipped), so a naive line count reports more gates than exist.
    """
    failures: list[str] = []
    for name, rel in HOOKS.items():
        path = repo_root / rel
        if not path.is_file():
            if name == "olivercode":
                failures.append(f"  [GATES] {rel} is missing")
            continue

        declared = GATE_DECL.findall(path.read_text(encoding="utf-8"))
        if not declared:
            failures.append(f"  [GATES] {rel} declares no 'Gate N/M' banners")
            continue

        totals = {int(total) for _, total in declared}
        if len(totals) > 1:
            failures.append(
                f"  [GATES] {rel} banners disagree on the total: {sorted(totals)}"
            )
            continue
        claimed = totals.pop()
        present = {int(num) for num, _ in declared}
        if len(present) != claimed:
            missing = sorted(set(range(1, claimed + 1)) - present)
            failures.append(
                f"  [GATES] {rel} claims {claimed} gates but only {len(present)} are present"
                + (f"; missing gate number(s): {missing}" if missing else "")
            )
    return failures


# Data loaders with no entry point. FEATURE_MAP states this exclusion explicitly, so
# the list here and the sentence there must agree -- that is the whole point of the check.
FEATURE_MAP_EXEMPT = {
    "scripts/lib/__init__.py",
    "scripts/lib/repo_profiles.py",
    "scripts/lib/token_policy.py",
}


def check_feature_map_completeness(repo_root: Path) -> list[str]:
    """FEATURE_MAP.md claims to index every capability. Hold it to that.

    The file says "If a capability exists and is not listed here, this map is wrong" --
    a testable invariant that nothing tested. Five scripts were missing when this was
    first run, three of them user-invocable QA checkers that CI itself calls.
    """
    fm_path = repo_root / "docs" / "FEATURE_MAP.md"
    if not fm_path.is_file():
        return ["  [FEATURE MAP] docs/FEATURE_MAP.md is missing"]
    fm = fm_path.read_text(encoding="utf-8")

    missing = [
        rel for rel in _tracked(repo_root, "scripts/")
        if rel not in FEATURE_MAP_EXEMPT and rel not in fm
    ]
    return [
        f"  [FEATURE MAP] {rel} is not listed in docs/FEATURE_MAP.md, which claims to index "
        f"every capability. Add a row, or add it to FEATURE_MAP_EXEMPT with the exclusion "
        f"stated in the doc too."
        for rel in sorted(missing)
    ]


# Skill names this repo ships that read like prose, so a bare mention is not a reference.
_NOT_A_CROSS_REF = {"plan", "tdd"}


def check_skill_cross_references(repo_root: Path) -> list[str]:
    """A skill naming a sibling skill must name one that exists.

    Deliberately narrow: only `skills/<name>` shaped references and backticked names
    that match the skill-name shape AND are cited alongside other real skill names.
    External slash-commands (/code-review, /simplify) are NOT checked -- they come from
    plugins that vary per machine, so gating them would fail on a fork that simply has
    a different toolset. A dangling `/ux-ui` did ship here, but the fix for that class
    is not naming machine-specific commands in a portable framework.
    """
    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        return []
    shipped = {p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()}

    failures: list[str] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        for match in re.findall(r"`skills/([a-z0-9-]+)`|`skills/([a-z0-9-]+)/SKILL\.md`", text):
            name = next(filter(None, match), None)
            if name and name not in shipped:
                failures.append(
                    f"  [SKILLS] {skill_md.parent.name} references skills/{name}, "
                    f"which this repo does not ship"
                )
    return failures


def check_all(repo_root: Path) -> list[str]:
    return (
        check_skill_index(repo_root)
        + check_gate_count(repo_root)
        + check_gate_integrity(repo_root)
        + check_gate_coverage_table(repo_root)
        + check_feature_map_completeness(repo_root)
        + check_skill_cross_references(repo_root)
    )
