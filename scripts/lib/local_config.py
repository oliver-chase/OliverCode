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
import sys
from pathlib import Path

OC_ROOT = Path(__file__).resolve().parent.parent.parent


def claude_dir() -> Path:
    """The operator's ~/.claude folder, resolved at call time so a test that sets HOME gets its own."""
    return Path.home() / ".claude"
LOCAL_FILE = OC_ROOT / "olivercode.local.json"
REAL_LOCAL_FILE = LOCAL_FILE

# A setting a release adds gets its default here. The saved value wins, so a default only fills a key the user never set.
DEFAULTS: dict = {"allowOutside": [], "allowedAuthors": [], "personalRepos": [], "deleteMergedRemoteBranches": False, "cityDeclined": False, "notifications": True, "maxBuilders": 1, "maxStorySpend": 6.0}
BACKLOG_CONFIG = "docs/backlog-config.json"
LOCAL_BACKLOG_CONFIG = "docs/backlog-config.local.json"  # git-ignored: the user's own repo and Project win over the tracked file


def load_local() -> dict:
    """The local file's contents. OLIVERCODE_LOCAL_CONFIG names another file; the test harness
    points it at /dev/null so no test reads this machine's real repo paths."""
    path = Path(os.environ["OLIVERCODE_LOCAL_CONFIG"]) if "OLIVERCODE_LOCAL_CONFIG" in os.environ else LOCAL_FILE
    if path == REAL_LOCAL_FILE and "unittest" in sys.modules and path.is_file():
        raise RuntimeError(f"a test read the real {path}; import tests/_support.py or set OLIVERCODE_LOCAL_CONFIG")
    if not path.is_file():
        return {}
    with open(path) as f:
        return json.load(f)


def delete_merged_remote_branches() -> bool:
    """True only when the owner set deleteMergedRemoteBranches in olivercode.local.json. The daily job lists merged origin branches and deletes them only with this."""
    return load_local().get("deleteMergedRemoteBranches") is True


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def private_repos() -> dict[str, Path]:
    """Private repos outside the fleet, by name: each gets the private hook variant, a hook
    check, a push and a backlog search."""
    repos = {name: Path(p).expanduser() for name, p in load_local().get("privateRepos", {}).items()}
    return repos


DEFAULT_FLEET_REGISTRY = "~/.olivercode/fleet/repo-profiles.json"
FLEET_NAME = "olivercode-fleet"  # the fleet repo's folder beside the checkout and its name on GitHub (#1057)


def fleet_home(oc_root: Path = OC_ROOT) -> Path:
    """Where install keeps the fleet repo: olivercode-fleet beside the OliverCode checkout, the same name init-fleet gives the GitHub copy (#1057).
    OLIVERCODE_FLEET_DIR names another folder, which the test harness uses so no test writes beside this checkout."""
    return Path(os.environ["OLIVERCODE_FLEET_DIR"]) if "OLIVERCODE_FLEET_DIR" in os.environ else Path(oc_root).parent / FLEET_NAME


def fleet_registry_path() -> Path:
    """Where this machine keeps the fleet registry: `fleetRegistry` in olivercode.local.json, else the default
    under ~/.olivercode. `olivercode init-fleet` creates the file there. The environment variable
    OLIVERCODE_FLEET_REGISTRY wins over both."""
    value = os.environ.get("OLIVERCODE_FLEET_REGISTRY") or load_local().get("fleetRegistry") or DEFAULT_FLEET_REGISTRY
    return Path(value).expanduser()


def _profile_count(path: Path) -> int:
    """How many profiles the registry file at path holds, 0 when it is missing or unreadable."""
    try:
        return len(json.loads(Path(path).read_text()).get("profiles", {}))
    except (OSError, ValueError, AttributeError):
        return 0


def link_default_registry(registry: Path) -> str:
    """Makes the default registry path a link to registry, so the default and the configured path read one file (#1083).
    Only a link already at the default path is repointed, so no folder is made under it. A stale link is replaced and a
    link already right is kept, so a repeat run never raises FileExistsError. A real file at the default path is the
    owner's and stays, as does a link whose target holds profiles when registry holds none, so a repoint never hides the
    owner's profiles. Returns what it did, or "" when nothing changed."""
    default = Path(DEFAULT_FLEET_REGISTRY).expanduser()
    registry = Path(registry).expanduser()
    if default == registry or not registry.is_file():
        return ""
    if default.is_symlink():
        if default.resolve() == registry.resolve():
            return ""
        if _profile_count(default) and not _profile_count(registry):
            return f"{default} links to {default.resolve()}, which holds profiles that {registry} lacks, so it was not repointed"
        default.unlink()
    elif default.exists():
        return f"{default} is a file of its own, so it was not linked to {registry}"
    else:
        return ""
    default.symlink_to(registry)
    return f"Linked {default} to {registry}"


def skills_root() -> Path | None:
    """The personal skills folder that health checks."""
    return _path(os.environ.get("OLIVERCODE_SKILLS_ROOT") or load_local().get("skillsRoot"))


def other_device() -> tuple[set[str], set[str]]:
    """(repo names, GitHub accounts) that belong to another of the owner's devices, lowercased.

    `otherDeviceRepos` names repos that never belong on this machine and `otherDeviceOwners` names the GitHub
    accounts or orgs whose repos stay off it. Every fleet walk skips the first, and `health` and the clone
    guard refuse a checkout of either (#637)."""
    local = load_local()
    return ({str(n).lower() for n in local.get("otherDeviceRepos", [])},
            {str(o).lower() for o in local.get("otherDeviceOwners", [])})


def repo_paths() -> dict[str, Path]:
    """Fleet repos that do not sit beside OliverCode on this machine, by profile name."""
    return {name: Path(p).expanduser() for name, p in load_local().get("repoPaths", {}).items()}


def voice_file(oc_root: Path = OC_ROOT) -> Path:
    """The voice file install links as ~/.claude/VOICE.md: the owner's own file when `voiceFile` (or
    OLIVERCODE_VOICE_FILE) names one that exists, else the neutral voice this checkout ships."""
    own = _path(os.environ.get("OLIVERCODE_VOICE_FILE") or load_local().get("voiceFile"))
    return own if own and own.is_file() else oc_root / "docs" / "VOICE.md"


def design_file(oc_root: Path = OC_ROOT) -> Path:
    """The design file install links as ~/.claude/DESIGN.md: the user's own file when `designFile` (or
    OLIVERCODE_DESIGN_FILE) names one that exists, else the design standard this checkout ships (#719)."""
    own = _path(os.environ.get("OLIVERCODE_DESIGN_FILE") or load_local().get("designFile"))
    return own if own and own.is_file() else oc_root / "docs" / "DESIGN.md"


def local_path() -> Path:
    """The file load_local reads: OLIVERCODE_LOCAL_CONFIG when set, else olivercode.local.json."""
    return Path(os.environ["OLIVERCODE_LOCAL_CONFIG"]) if "OLIVERCODE_LOCAL_CONFIG" in os.environ else LOCAL_FILE


def save_local(updates: dict) -> None:
    """Merge `updates` into the local file and keep every other key. Refuses /dev/null, which means no file."""
    path = local_path()
    if str(path) == os.devnull:
        raise RuntimeError("no local config file in use (OLIVERCODE_LOCAL_CONFIG is /dev/null)")
    data = json.loads(path.read_text()) if path.is_file() else {}
    data.update(updates)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def settings() -> dict:
    """Every setting: the shipped DEFAULTS with the user's saved values on top, so only a missing key takes a default."""
    return {**DEFAULTS, **load_local()}


def setting(key: str):
    """One setting: the user's saved value, else the default a release ships, else None."""
    return settings().get(key)


def saved_builders() -> int:
    """Temporary hard cap: saved configuration cannot raise Claude concurrency above one."""
    return 1


def max_builders() -> int:
    """Temporary hard cap for every OliverCode model invocation."""
    return 1


def max_story_attempts() -> int:
    """Temporary ceiling: no more than four model invocations per story, regardless of saved overrides."""
    value = setting("maxStoryAttempts")
    return min(value, 4) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 4


def max_story_spend() -> float:
    """Temporary ceiling: recorded spend cannot exceed $3 per story, regardless of saved overrides."""
    value = setting("maxStorySpend")
    return min(float(value), 3.0) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 3.0


def _overlay(base: dict, top: dict) -> dict:
    """base with top's values on top, merging nested objects key by key."""
    out = dict(base)
    for key, value in top.items():
        out[key] = _overlay(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def has_backlog_config(repo: Path) -> bool:
    """True when the repo holds the tracked backlog config or the user's own local one."""
    return (Path(repo) / BACKLOG_CONFIG).is_file() or (Path(repo) / LOCAL_BACKLOG_CONFIG).is_file()


def backlog_config(repo: Path) -> dict:
    """The repo's backlog config: the tracked docs/backlog-config.json with the git-ignored
    docs/backlog-config.local.json on top, so a user who cannot push names their own repo and Project
    without editing a tracked file. Raises OSError or ValueError as reading one file would."""
    tracked, local = Path(repo) / BACKLOG_CONFIG, Path(repo) / LOCAL_BACKLOG_CONFIG
    base = json.loads(tracked.read_text(encoding="utf-8")) if tracked.is_file() or not local.is_file() else {}
    if local.is_file():
        base = _overlay(base, json.loads(local.read_text(encoding="utf-8")))
    return base
