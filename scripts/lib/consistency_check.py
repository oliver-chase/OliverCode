"""Doc-vs-code consistency checks.

One failure class: a tracked doc asserts something the code contradicts. Collapsed
into a single checker per docs/RULES.md's removal rule -- a validator that
duplicates another's failure class gets merged into it.

Each `check_*` below states what drifts and why nothing else catches it. Gate counts
are per-repo-type, so a claim resolves to its own hook before being compared:
GATE-COUNT-1 in docs/DECISIONS.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lib.gitfiles import tracked_files
from lib.skills_catalog import skill_dirs

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
# pattern would miss a headline claim such as "8 pre-commit gates", where the
# number is not adjacent to the noun. Modifiers must be alphabetic, so "6 of the 8
# gates" binds to the 8 and the 6 is not read as a total.
GATE_CLAIM = re.compile(
    r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+(?:[a-z][a-z-]*\s+){0,3}gates\b",
    re.IGNORECASE,
)


def _claimed_count(token: str) -> int | None:
    """Normalize a digit or number-word to an int; None if neither."""
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


def check_skill_index(repo_root: Path) -> list[str]:
    """skills/INDEX.md's table must match the skills/*/SKILL.md directories both ways,
    and each SKILL.md's frontmatter `name:` must match its directory.

    The launcher reads the frontmatter and humans read the table, so the two drift
    apart with nothing reporting it.
    """
    failures: list[str] = []
    skills_dir = repo_root / "skills"
    index_path = skills_dir / "INDEX.md"
    if not index_path.is_file():
        return ["  [SKILLS] skills/INDEX.md is missing"]

    on_disk = {p.name for p in skill_dirs(skills_dir)}
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
# Gate coverage is NOT uniform per repo type. docs/GATES.md holds the table, and
# the tests pin the totals — restating numbers here would just be a third copy to drift.
HOOKS = {
    "olivercode": Path(".githooks/pre-commit"),
    "template": Path("core/templates/project/pre-commit"),
    "template-private": Path("core/templates/project/pre-commit-private"),
}
# Checked most-specific first: "private" wins over a bare mention of "template".
_HOOK_CUES = (
    ("template-private", ("private variant", "pre-commit-private", "private template")),
    # "registered"/"governed" repo are what the launcher and validate.sh call a fleet
    # repo in their own output, so docs reach for them naturally.
    ("template", ("template", "adopted repo", "fleet repo", "product repo",
                  "downstream", "core/templates", "project repo",
                  "registered repo", "governed repo")),
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
    """Which hook a gate-count claim refers to, from the doc path and the claim's own line."""
    haystack = " ".join((rel, line)).lower()
    for hook, cues in _HOOK_CUES:
        if any(cue in haystack for cue in cues):
            return hook
    return "olivercode"


def check_gate_count(repo_root: Path) -> list[str]:
    """No tracked doc may claim a gate count the corresponding hook contradicts.

    Resolves each claim to the hook it is ABOUT, so a doc that tells forkers their repos
    get eight gates is compared with the template's six and not with OliverCode's own
    eight. GATE-COUNT-1 in docs/DECISIONS.md has the reasoning.
    """
    totals, failures = _hook_totals(repo_root)
    if not totals:
        return failures

    for rel in tracked_files(repo_root, "*.md"):
        lines = (repo_root / rel).read_text(encoding="utf-8").splitlines()
        for line in lines:
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
    """docs/GATES.md's per-repo Total row must match the real hooks.

    That table is the single home for gate coverage and every other doc points at it,
    so a stale row propagates everywhere by design.
    """
    doc = repo_root / "docs" / "GATES.md"
    if not doc.is_file():
        return ["  [GATES] docs/GATES.md is missing — it holds the gate coverage table"]

    row = next(
        (l for l in doc.read_text(encoding="utf-8").splitlines()
         if l.lstrip().startswith("| **Total**")),
        None,
    )
    if row is None:
        return [
            "  [GATES] docs/GATES.md has no '| **Total** |' row in its gate coverage "
            "table — that row is what pins the per-repo counts to the hooks"
        ]

    stated = [int(n) for n in re.findall(r"\*\*(\d+)\*\*", row)]
    totals, failures = _hook_totals(repo_root)
    expected = [totals.get(h) for h in ("olivercode", "template", "template-private")]
    expected = [e for e in expected if e is not None]
    if stated != expected:
        failures.append(
            f"  [GATES] docs/GATES.md's coverage table totals {stated} but the hooks "
            f"have {expected} (OliverCode, adopted repo, private variant)"
        )
    return failures


def check_contract_reachability(repo_root: Path) -> list[str]:
    """Every contract is pointed AT by something. A contract nothing references is
    worse than a deleted one: it stays in the tree, drifts because no reader arrives,
    then gets cited later as if it were current.

    `PUBLIC_PRIVATE_REPO_STANDARD.md` was in exactly that state -- a real, active rule
    no doc, script, hook or manifest named. Reference and link checks could not see it,
    because both verify that a path MENTIONED somewhere resolves, and nothing mentioned
    it at all.
    """
    contracts_dir = repo_root / "core" / "contracts"
    if not contracts_dir.is_dir():
        return []

    # No pathspec. `git ls-files ""` matches nothing, which would silently compare each
    # contract against an empty corpus and report every one as an orphan.
    #
    # This file is excluded from the corpus it searches. The docstring above names a
    # contract as its worked example, which made the checker satisfy its own check and
    # report clean with the real reference deleted.
    self_rel = "scripts/lib/consistency_check.py"
    tracked = [f for f in tracked_files(repo_root) if f != self_rel]
    orphans = []
    for rel in sorted(tracked_files(repo_root, "core/contracts/")):
        name = Path(rel).name
        if not name.endswith(".md"):
            continue
        # Any tracked file other than the contract itself. Hooks and manifests count:
        # a shell error message pointing a reader at the rule is a real reference.
        referenced = any(
            other != rel and name in (repo_root / other).read_text(encoding="utf-8", errors="ignore")
            for other in tracked
            if (repo_root / other).is_file()
        )
        if not referenced:
            orphans.append(rel)

    return [
        f"  [CONTRACT ORPHAN] {rel} is referenced by no other tracked file. Point at it "
        f"from a doc, or delete it -- an unreferenced contract is one the "
        f"next reader will treat as current without knowing whether it is."
        for rel in orphans
    ]


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
    shipped = {p.name for p in skill_dirs(skills_dir)}

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
        + check_gate_coverage_table(repo_root)
        + check_contract_reachability(repo_root)
        + check_skill_cross_references(repo_root)
    )
