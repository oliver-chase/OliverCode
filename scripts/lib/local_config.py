"""This machine's paths, kept out of every tracked file.

Where the vault, the personal skills folder and any repo outside the sibling layout
live differs per machine. Tracked files that named them broke on every folder move,
so they live in `olivercode.local.json` at the OliverCode root (gitignored; see
`olivercode.local.example.json`) or in environment variables, which win.

An unset value means that piece is not on this machine. The commands that need it
say so once and move on; nothing guesses a location from the folder layout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

OC_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_FILE = OC_ROOT / "olivercode.local.json"


def load_local() -> dict:
    if not LOCAL_FILE.is_file():
        return {}
    with open(LOCAL_FILE) as f:
        return json.load(f)


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def vault_root() -> Path | None:
    """The vault repo, a hook and push target outside the fleet."""
    return _path(os.environ.get("OLIVERCODE_VAULT_ROOT") or load_local().get("vaultRoot"))


def skills_root() -> Path | None:
    """The personal skills folder that health and audit-fleet check."""
    return _path(os.environ.get("OLIVERCODE_SKILLS_ROOT") or load_local().get("skillsRoot"))


def repo_paths() -> dict[str, Path]:
    """Fleet repos that do not sit beside OliverCode on this machine, by profile name."""
    return {name: Path(p).expanduser() for name, p in load_local().get("repoPaths", {}).items()}


def push_repos() -> list[str]:
    """Profile names push-fleet pushes in addition to OliverCode and the vault."""
    return list(load_local().get("pushRepos", []))
