"""One check of the skill links in a folder such as ~/.claude/skills, shared by the launcher and the health run."""

from __future__ import annotations

from pathlib import Path


def link_state(link: Path, expected: Path) -> str:
    """Return how `link` stands against the skill folder it should point at.

    "absent" is nothing at that path, "real" is a file or folder that is not a link,
    "broken" is a link to nothing, "elsewhere" is a live link to a different folder, and
    "ok" is a link that resolves to `expected`.
    """
    if not link.is_symlink():
        return "real" if link.exists() else "absent"
    if not link.exists():
        return "broken"
    return "ok" if link.resolve() == expected.resolve() else "elsewhere"


def link_states(expected: dict[str, Path], links_dir: Path) -> dict[str, str]:
    """Map each expected skill name to its `link_state` under `links_dir`."""
    return {name: link_state(links_dir / name, target) for name, target in expected.items()}


def broken_links(links_dir: Path) -> list[str]:
    """Names of links in `links_dir` that point at nothing, sorted."""
    return sorted(p.name for p in links_dir.iterdir() if p.is_symlink() and not p.exists())
