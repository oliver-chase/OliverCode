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

# Every key this version reads, with the default a release ships (None where the code finds its own, such as repoRoot).
# Install removes any saved key not listed here (#1295), so a key the code starts reading is listed here in the same change.
DEFAULTS: dict = {
    "allowOutside": [], "allowedAuthors": [], "auditMode": None, "city": False, "deleteMergedRemoteBranches": False,
    "designFile": None, "engineBranch": None, "fleetRegistry": None, "liveCopies": {}, "maxBuilders": None,
    "otherDeviceOwners": [], "otherDeviceRepos": [], "privateRepos": {}, "repoPaths": {}, "repoRoot": None, "schedules": {},
    "skillsRoot": None, "voiceFile": None, "watchRoots": None,
}
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
    """Private repos, by name: each gets the private hook variant, a hook
    check, a push and a backlog search."""
    repos = {name: Path(p).expanduser() for name, p in load_local().get("privateRepos", {}).items()}
    return repos


def skills_root() -> Path | None:
    """The personal skills folder that health checks."""
    return _path(os.environ.get("OLIVERCODE_SKILLS_ROOT") or load_local().get("skillsRoot"))


def other_device() -> tuple[set[str], set[str]]:
    """(repo names, GitHub accounts) that belong to another of the owner's devices, lowercased.

    `otherDeviceRepos` names repos that never belong on this machine and `otherDeviceOwners` names the GitHub
    accounts or orgs whose repos stay off it. The clone guard and `health` refuse a checkout of either (#637)."""
    local = load_local()
    return ({str(n).lower() for n in local.get("otherDeviceRepos", [])},
            {str(o).lower() for o in local.get("otherDeviceOwners", [])})


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


def default_builders(cores: int | None = None, mem_gb: int | None = None) -> int:
    """The builder limit with no saved value: half the cores or the memory in GB less 4, whichever is smaller, never below 1.
    A builder session holds 150 to 350 MB and mostly waits on the model, and 4 GB stays free for the system and the one validation run (#1055)."""
    cores = cores or os.cpu_count() or 1
    if mem_gb is None:
        try:
            mem_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 2**30
        except (ValueError, OSError, AttributeError):  # a platform without sysconf gets the 8 GB this default was measured on
            mem_gb = 8
    return max(1, min(cores // 2, mem_gb - 4))


def max_builders() -> int:
    """The machine-wide builder limit drain and dispatch share: maxBuilders in the local file, else the default for this machine."""
    saved = setting("maxBuilders")
    if isinstance(saved, int) and not isinstance(saved, bool) and saved >= 1:
        return saved
    return default_builders()


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
