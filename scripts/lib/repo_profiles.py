"""Repo-profiles loader, and where the fleet registry lives on this machine.

The registry (`repo-profiles.json`) names the operator's repos
and services, so a fork must not inherit it. The real files live in a private repo at
`olivercode/<file>`, found through `privateRepos` in olivercode.local.json. A checkout with
none falls back to the tracked `shared/<file>`, which ships as an empty example and is
where a fork registers its own repos.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.local_config import OC_ROOT, private_repos, repo_paths

REGISTRY_DIR = "olivercode"


REGISTRY_NAME = "repo-profiles.json"


def registry_file(repo_root: Path) -> Path:
    """The registry file this checkout reads: a private repo's copy, else the tracked one.

    Only the checkout whose olivercode.local.json names the private repos looks there, so a
    test or a fork run against another root reads that root's own `shared/` file.
    """
    if Path(repo_root).resolve() == OC_ROOT.resolve():
        for repo in private_repos().values():
            candidate = repo / REGISTRY_DIR / REGISTRY_NAME
            if candidate.is_file():
                return candidate
    return Path(repo_root) / "shared" / REGISTRY_NAME


def registry_gap(repo_root: Path) -> str:
    """Why this checkout reads no real registry although it names private repos, or ""."""
    private = private_repos() if Path(repo_root).resolve() == OC_ROOT.resolve() else {}
    if not private or registry_file(repo_root) != Path(repo_root) / "shared" / "repo-profiles.json":
        return ""
    names = ", ".join(f"{n} ({p})" for n, p in private.items())
    return (f"no private repo holds {REGISTRY_DIR}/repo-profiles.json, so the fleet reads as empty. Checked: {names}. "
            "Name the repo that holds it under privateRepos in olivercode.local.json")


def load_repo_profiles(repo_root):
    """Return (profiles: dict, source_path: Path)."""
    path = registry_file(repo_root)
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
    or relative to fleet_root. This machine's own `repoPaths` (local_config) wins over
    both, so a tracked profile never has to name one machine's folders.
    """
    local = repo_paths().get(name)
    if local:
        return local
    declared = profile.get("path")
    if not declared:
        return fleet_root / name
    p = Path(declared).expanduser()
    return p if p.is_absolute() else (fleet_root / p)


def configured_location(name: str, profile: dict) -> str | None:
    """The config entry that names where `name` lives, or None when nothing does.

    A repo with an entry has been placed on purpose, so a missing folder there means it moved.
    A repo with none only sits at the default spot, and its absence means it was never cloned.
    """
    if name in repo_paths():
        return f"repoPaths.{name} in olivercode.local.json"
    if profile.get("path"):
        return f"profiles.{name}.path in repo-profiles.json"
    return None


def iter_fleet(profiles: dict, fleet_root: Path):
    """Yield (name, profile, repo_path) for every fleet repo, framework repo excluded.

    Health and sync-hooks share this one filter. It compares the self-skip
    case-insensitively, so a profile named "OliverCode" -- the casing `discover` emits
    from a directory name -- is skipped by both.
    """
    for name, profile in profiles.items():
        if name.lower() == "olivercode":
            continue
        yield name, profile, resolve_repo_path(name, profile, fleet_root)
