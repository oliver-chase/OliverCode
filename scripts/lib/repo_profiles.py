"""Repo-profiles loader.

`shared/repo-profiles.json` is tracked and holds the real fleet (repo names,
validation commands, keepalive config). One file, real data, no local overlay --
this is a single-operator framework across this operator's own accounts, not a
project shared with strangers who'd need a placeholder to start from.
"""

import json
from pathlib import Path


def load_repo_profiles(repo_root):
    """Return (profiles: dict, source_path: Path)."""
    path = repo_root / "shared" / "repo-profiles.json"
    with open(path) as f:
        data = json.load(f)
    return data.get("profiles", {}), path


def resolve_repo_path(name: str, profile: dict, fleet_root: Path) -> Path:
    """Where a fleet repo actually lives.

    Default is the sibling convention `<fleet_root>/<name>`, which assumes every repo
    sits under one parent. That assumption breaks the moment someone adopts this into
    an existing setup whose repos are spread across several directories -- and before
    this existed, such a repo could not be registered at all, because the name WAS the
    path. An optional `path` in the profile takes precedence: absolute, `~`-relative,
    or relative to fleet_root.
    """
    declared = profile.get("path")
    if not declared:
        return fleet_root / name
    p = Path(declared).expanduser()
    return p if p.is_absolute() else (fleet_root / p)


def iter_fleet(profiles: dict, fleet_root: Path):
    """Yield (name, profile, repo_path) for every fleet repo, framework repo excluded.

    Single definition on purpose. health and sync-hooks previously each carried their
    own copy of this filter and had already drifted apart: one compared the self-skip
    case-sensitively and the other did not, so a profile named "OliverCode" -- the
    casing `discover` emits from a directory name -- was skipped by sync-hooks and
    treated as a governed repo by health. Moved here 2026-09-15 so a third caller
    (find-spec.py) does not become a third copy to drift.
    """
    for name, profile in profiles.items():
        if name.lower() == "olivercode":
            continue
        yield name, profile, resolve_repo_path(name, profile, fleet_root)
