"""Skill discovery: read every skills/*/SKILL.md's frontmatter.

The launcher re-exports both names, so the catalog logic is importable and testable on its own.
"""

from __future__ import annotations

from pathlib import Path

def _parse_skill_frontmatter(skill_md: Path) -> tuple[str, str]:
    """Extract (name, description) from a SKILL.md's YAML frontmatter.

    A small hand-rolled parser avoids a PyYAML dependency: this repo's frontmatter is a
    narrow subset (flat `key: value` pairs, optional `>`/`>-` folded block
    scalars for `description`) and stays that way by convention.
    """
    name = skill_md.parent.name
    description = ""
    try:
        lines = skill_md.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return name, description
    if not lines or lines[0].strip() != "---":
        return name, description
    try:
        end = lines.index("---", 1)
    except ValueError:
        return name, description
    frontmatter = lines[1:end]

    i = 0
    while i < len(frontmatter):
        line = frontmatter[i]
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'") or name
            i += 1
            continue
        if line.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            if rest in (">", ">-", "|", "|-"):
                folded: list[str] = []
                i += 1
                while i < len(frontmatter) and (frontmatter[i].startswith(" ") or not frontmatter[i].strip()):
                    folded.append(frontmatter[i].strip())
                    i += 1
                description = " ".join(part for part in folded if part)
                continue
            description = rest.strip("\"'")
            i += 1
            continue
        i += 1
    return name, description

def _load_skills(oc_root: Path) -> list[tuple[str, str]]:
    """Every skill in skills/: (name, description), sorted by name.

    Reads SKILL.md frontmatter directly. INDEX.md is for humans browsing by
    category, and the frontmatter is the always-accurate source because it
    cannot drift from the skills it describes.
    """
    skills_dir = oc_root / "skills"
    entries: list[tuple[str, str]] = []
    if not skills_dir.is_dir():
        return entries
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        entries.append(_parse_skill_frontmatter(skill_md))
    return sorted(entries, key=lambda pair: pair[0])
