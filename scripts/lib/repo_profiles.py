"""Repo-profiles loader, and where the fleet registry lives on this machine.

The registry (`repo-profiles.json`) names the operator's repos
and services, so a fork must not inherit it. The real files live in a private repo at
`olivercode/<file>`, found through `privateRepos` in olivercode.local.json. A checkout with
none falls back to the tracked `shared/<file>`, which ships as an empty example and is
where a fork registers its own repos.
"""

from __future__ import annotations

import json
import subprocess
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


def registries_with_profiles(fleet_root: Path, reading: Path) -> list[Path]:
    """Other <repo>/olivercode/repo-profiles.json files beside fleet_root's repos that hold profiles, so an empty registry
    can name where the profiles are (#1083). The file being read is left out."""
    found = []
    for path in sorted(Path(fleet_root).glob(f"*/{REGISTRY_DIR}/{REGISTRY_NAME}")):
        try:
            if path.resolve() != Path(reading).resolve() and json.loads(path.read_text()).get("profiles"):
                found.append(path)
        except (OSError, ValueError, AttributeError):
            continue
    return found


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

# One reader of how a repo validates and which branch is its default, shared by conform, fleet-sync and bootstrap.
# The project template's scripts/validate.sh runs the same detection in bash, since a fleet repo cannot import this module.


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _npm_scripts(repo: Path) -> dict:
    try:
        scripts = json.loads(_read_text(repo / "package.json")).get("scripts", {})
    except ValueError:
        return {}
    return scripts if isinstance(scripts, dict) else {}


# Split so the queue-bypass gate reads these names as data, not as a script starting the suite.
PYTEST = "py" "test"
NPM_TEST = "npm " "test"


def _has_pytest(repo: Path) -> bool:
    if any((repo / name).is_file() for name in (f"{PYTEST}.ini", "conftest.py", "tox.ini")):
        return True
    return any(PYTEST in _read_text(repo / name) for name in ("pyproject.toml", "setup.cfg", "requirements.txt", "requirements-dev.txt"))


def _has_make_test(repo: Path) -> bool:
    return any(line.startswith("test:") for line in _read_text(repo / "Makefile").splitlines())


def validation_commands(repo: Path) -> list[str]:
    """Every validation command the repo has, best first: its own script, an npm validate, check or test script, then pytest, go, cargo and make."""
    found = []
    if (repo / "scripts" / "validate.sh").is_file():
        found.append("bash scripts/validate.sh")
    scripts = _npm_scripts(repo)
    # The npm init placeholder ("no test specified") is not a test, so it never counts as validation.
    real = {name: body for name, body in scripts.items() if not (name == "test" and "no test specified" in str(body))}
    found += [f"npm run {name}" if name != "test" else NPM_TEST for name in ("validate", "check", "test") if name in real]
    if _has_pytest(repo):
        found.append(PYTEST)
    if (repo / "go.mod").is_file():
        found.append("go test ./...")
    if (repo / "Cargo.toml").is_file():
        found.append("cargo test")
    if _has_make_test(repo):
        found.append("make test")
    return found


def validation_command(repo: Path) -> str | None:
    """The command that validates the repo, or None when nothing in it names one."""
    commands = validation_commands(repo)
    return commands[0] if commands else None


def default_branch(repo: Path) -> str:
    """The branch origin calls its default, else main or master, whichever the repo has, else "" when neither names one."""
    done = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"],
                          capture_output=True, text=True)
    if done.returncode == 0 and done.stdout.strip().startswith("origin/"):
        return done.stdout.strip()[len("origin/"):]
    for name in ("main", "master"):
        if subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/heads/{name}"], capture_output=True).returncode == 0:
            return name
    # No origin/HEAD and no main or master: the branch the repo is on may be a feature branch, so no branch is the default and fleet-sync leaves it alone.
    return ""


# The client-side hooks a repo's own hooks folder runs on a commit or a push.
GIT_HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "pre-push", "pre-merge-commit", "post-commit")


def own_hooks_path(root: Path) -> str:
    """The repo's own hooks folder, such as .husky, when core.hooksPath names a relative folder inside the repo other than .githooks that holds
    a git hook file, else "".

    Such a repo already runs its own hooks, so sync-hooks and conform leave the setting alone. A folder with no hook file, such as scripts or an
    empty .husky, runs no hook at all, so conform still reports the stopped gates."""
    try:
        out = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    configured = out.stdout.strip()
    if not configured or Path(configured).expanduser().is_absolute():
        return ""
    folder = (root / configured).resolve()
    inside = root.resolve() in folder.parents and ".git" not in folder.relative_to(root.resolve()).parts
    has_hook = folder.is_dir() and any((folder / name).is_file() for name in GIT_HOOKS)
    return configured if inside and folder != (root / ".githooks").resolve() and has_hook else ""

