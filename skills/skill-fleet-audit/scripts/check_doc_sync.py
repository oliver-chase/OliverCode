#!/usr/bin/env python3
"""Flags drift between the live skill fleet and the docs that describe it.

Two checks, each catching a real bug this fleet has shipped:

1. README rows vs. disk. `README.md` is the canonical per-skill map: one `| `name` | description |`
   table row per skill. A skill on disk with no row, or a row naming a skill that is not on disk,
   is drift. A deleted skill stays named in prose nobody re-checks.
2. Symlink health. Every skill on disk has a `~/.claude/skills/<name>` symlink that resolves back to
   it. A missing or misresolving symlink means the skill is on disk but not invocable.

`check_readme_facts.py` checks the README's tree and dependency table. This check blocks a
commit. It never fixes anything.

Usage:
    check_doc_sync.py                 # scan every skill under the fleet root
    check_doc_sync.py <path-or-dir>   # scan one folder

Tests: python3 -m unittest test_check_doc_sync   (from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = FLEET_ROOT = _fleet.FLEET_ROOT
README_FILE = FLEET_ROOT / "README.md"
SYMLINK_ROOT = Path.home() / ".claude" / "skills"

TABLE_ROW_RE = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`\s*\|")

# README.md's "## Dependency model" section tables family folders in this same
# backtick-quoted-table-row shape a per-skill row uses -- a name there is never a skill row.
# Scoped to that section by heading range, not by name: a family can share its name with
# its own single skill, which has a real per-skill row elsewhere.
DEPENDENCY_GRAPH_HEADING = re.compile(r"^##\s+Dependency (graph|model)")
SECTION_HEADING = re.compile(r"^##\s+")


def readme_skill_names():
    """Every skill name named as a table row's first backticked cell in README.md.

    Not scoped to SKILLS_ROOT's subset -- README.md always describes the whole fleet, so a
    partial `check_doc_sync.py <subfolder>` run still diffs against the full README for
    correctness (a stale README row for a skill outside the scanned subfolder is still real
    drift, just not this run's problem to report -- filtered out by the caller).
    """
    if not README_FILE.exists():
        return None
    names = set()
    in_dependency_graph = False
    for line in README_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if DEPENDENCY_GRAPH_HEADING.match(stripped):
            in_dependency_graph = True
            continue
        if in_dependency_graph and SECTION_HEADING.match(stripped):
            in_dependency_graph = False
        if in_dependency_graph:
            continue
        m = TABLE_ROW_RE.match(stripped)
        if m:
            names.add(m.group(1))
    return names


def check_symlink(name, real_path):
    link = SYMLINK_ROOT / name
    if not link.is_symlink() and not link.exists():
        return f"no symlink at ~/.claude/skills/{name}"
    try:
        resolved = link.resolve()
    except OSError:
        return f"~/.claude/skills/{name} is broken (cannot resolve)"
    if resolved != real_path.resolve():
        return f"~/.claude/skills/{name} resolves to {resolved}, not {real_path}"
    return None


def main(argv=None):
    global SKILLS_ROOT
    SKILLS_ROOT = _fleet.scan_root(sys.argv[1:] if argv is None else argv, SKILLS_ROOT)
    skills = sorted((p.name, p) for p in _fleet.find_skills(SKILLS_ROOT))
    readme_names = readme_skill_names()
    problems = []
    advisory_skip = []

    if readme_names is None:
        advisory_skip.append(f"{README_FILE} not found -- skipping README-row check")
    else:
        disk_names = {name for name, _ in skills}
        missing_from_readme = disk_names - readme_names
        for name in sorted(missing_from_readme):
            problems.append(f"{name}: on disk, no `{name}` table row found in README.md")
        # Only meaningful for a full fleet-wide run -- a scoped run's disk_names is a subset
        # of the fleet, so a README name outside that subset is not this run's drift to find.
        if SKILLS_ROOT == FLEET_ROOT:
            stale_in_readme = readme_names - disk_names
            for name in sorted(stale_in_readme):
                problems.append(f"README.md names `{name}`, no matching skill folder on disk")

    for name, path in skills:
        issue = check_symlink(name, path)
        if issue:
            problems.append(f"{name}: {issue}")

    print(f"Doc-sync check: {len(skills)} skill(s) under {SKILLS_ROOT.name}/\n")
    for line in advisory_skip:
        print(f"[INFO] {line}")
    if advisory_skip:
        print()

    if problems:
        print(f"-- {len(problems)} problem(s) (advisory -- read and judge, never auto-fixed) --")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)

    print("Doc-sync clean: every skill has a README row and a working symlink.")


if __name__ == "__main__":
    main()
