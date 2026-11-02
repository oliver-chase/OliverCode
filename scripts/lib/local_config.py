"""This machine's paths, kept out of every tracked file.

Where the private repos, the personal skills folder and any repo outside the sibling layout
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
    """The local file's contents. OLIVERCODE_LOCAL_CONFIG names another file; the test harness
    points it at /dev/null so no test reads this machine's real repo paths."""
    path = Path(os.environ["OLIVERCODE_LOCAL_CONFIG"]) if "OLIVERCODE_LOCAL_CONFIG" in os.environ else LOCAL_FILE
    if not path.is_file():
        return {}
    with open(path) as f:
        return json.load(f)


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def private_repos() -> dict[str, Path]:
    """Private repos outside the fleet, by name: each gets the private hook variant, a hook
    check, a push and a backlog search."""
    repos = {name: Path(p).expanduser() for name, p in load_local().get("privateRepos", {}).items()}
    return repos


def skills_root() -> Path | None:
    """The personal skills folder that health and audit-fleet check."""
    return _path(os.environ.get("OLIVERCODE_SKILLS_ROOT") or load_local().get("skillsRoot"))


def repo_paths() -> dict[str, Path]:
    """Fleet repos that do not sit beside OliverCode on this machine, by profile name."""
    return {name: Path(p).expanduser() for name, p in load_local().get("repoPaths", {}).items()}
