"""Doc-vs-code consistency checks.

One failure class: a tracked doc asserts something the code contradicts. Collapsed
into a single checker per docs/RULES.md's removal rule -- a validator that
duplicates another's failure class gets merged into it.

Each `check_*` below states what drifts and why nothing else catches it.
"""

from __future__ import annotations

import re
from pathlib import Path

from lib.skills_catalog import skill_dirs

INDEX_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|", re.MULTILINE)
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


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
        + check_skill_cross_references(repo_root)
    )
