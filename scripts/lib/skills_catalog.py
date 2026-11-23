"""Skill discovery: the skill folders install and health read."""

from __future__ import annotations

from pathlib import Path


def skill_dirs(skills_dir: Path) -> list[Path]:
    """The skill folders under skills_dir: each directory that holds a SKILL.md, sorted by name."""
    return sorted(p for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
