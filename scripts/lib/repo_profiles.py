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

from lib import repo_state
from lib.local_config import DEFAULT_FLEET_REGISTRY, OC_ROOT, fleet_registry_path, other_device, private_repos, repo_paths

REGISTRY_DIR = "olivercode"


REGISTRY_NAME = "repo-profiles.json"
LOCAL_REGISTRY_NAME = "repo-profiles.local.json"  # git-ignored: `discover --register` writes the user's repo names here


def _configured_registry() -> Path | None:
    """The registry file `fleetRegistry` names, or None when it is missing or resolves to a tracked shared/ example (#845)."""
    configured = fleet_registry_path()
    if not configured.is_file():
        return None
    target = configured.resolve()
    if target.name == REGISTRY_NAME and target.parent.name == "shared" and (target.parent.parent / "scripts" / "olivercode").is_file():
        return None
    return configured


def registry_file(repo_root: Path) -> Path:
    """The registry file this checkout reads: a private repo's copy, else the tracked one.

    Only the checkout whose olivercode.local.json names the private repos looks there, so a
    test or a fork run against another root reads that root's own `shared/` file.
    """
    if Path(repo_root).resolve() == OC_ROOT.resolve():
        configured = _configured_registry()
        if configured:
            return configured
        for repo in private_repos().values():
            candidate = repo / REGISTRY_DIR / REGISTRY_NAME
            if candidate.is_file():
                return candidate
    local = Path(repo_root) / "shared" / LOCAL_REGISTRY_NAME
    return local if local.is_file() else Path(repo_root) / "shared" / REGISTRY_NAME


def registry_write_file(repo_root: Path) -> Path:
    """Where `discover --register` writes: the registry a private repo holds, else the ignored local file, never the tracked example."""
    path = registry_file(repo_root)
    if path == Path(repo_root) / "shared" / REGISTRY_NAME:
        return Path(repo_root) / "shared" / LOCAL_REGISTRY_NAME
    return path


NO_FLEET = ("no fleet is set. Run `olivercode init-fleet` to create one, or name an existing registry with "
            "`fleetRegistry` in olivercode.local.json (default " + DEFAULT_FLEET_REGISTRY + ")")


def registry_gap(repo_root: Path) -> str:
    """Why this checkout reads no real registry although it names private repos, or ""."""
    private = private_repos() if Path(repo_root).resolve() == OC_ROOT.resolve() else {}
    if not private or registry_file(repo_root).parent != Path(repo_root) / "shared":
        return ""
    names = ", ".join(f"{n} ({p})" for n, p in private.items())
    return (f"no private repo holds {REGISTRY_DIR}/repo-profiles.json, so the fleet reads as empty. Checked: {names}. "
            "Name the repo that holds it under privateRepos in olivercode.local.json")


def load_local_profiles(repo_root: Path) -> dict:
    """The profiles in the registry this checkout reads, or {} when it is missing or unreadable."""
    try:
        return json.loads(registry_file(repo_root).read_text()).get("profiles", {})
    except (OSError, ValueError):
        return {}


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


def iter_fleet(profiles: dict, fleet_root: Path, skip_archived: bool = True):
    """Yield (name, profile, repo_path) for every fleet repo, framework repo excluded.

    A repo that belongs to another device (`otherDeviceRepos`, or an origin in `otherDeviceOwners`, see
    local_config.other_device) is never yielded, so no fleet walk touches it (#637).

    A repo GitHub archived or deleted is skipped with one line (lib/repo_state.py), so every fleet walk
    leaves it alone. A caller that only looks a repo up by path passes skip_archived=False.

    Health and sync-hooks share this one filter. It compares the self-skip
    case-insensitively, so a profile named "OliverCode" -- the casing `discover` emits
    from a directory name -- is skipped by both.
    """
    other_repos, other_owners = other_device()
    for name, profile in profiles.items():
        if name.lower() == "olivercode" or name.lower() in other_repos:
            continue
        path = resolve_repo_path(name, profile, fleet_root)
        if other_owners and (path / ".git").exists() and (repo_state.origin(path) or "/").split("/")[0].lower() in other_owners:
            continue
        if skip_archived and (path / ".git").exists() and repo_state.skipped(name, path):
            continue
        yield name, profile, path
