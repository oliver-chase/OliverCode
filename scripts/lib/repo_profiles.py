"""How a repo validates, which branch is its default and whether it runs its own git hooks.

One reader of each. The stopped-hook check in health uses own_hooks_path. The project template's scripts/validate.sh runs the same
validation detection in bash, since a downstream repo cannot import this module.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
    # No origin/HEAD and no main or master: the branch the repo is on may be a feature branch, so no branch is the default.
    return ""


# The client-side hooks a repo's own hooks folder runs on a commit or a push.
GIT_HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "pre-push", "pre-merge-commit", "post-commit")


def own_hooks_path(root: Path) -> str:
    """The repo's own hooks folder, such as .husky, when core.hooksPath names a relative folder inside the repo other than .githooks that holds
    a git hook file, else "".

    Such a repo already runs its own hooks, so sync-hooks leaves the setting alone. A folder with no hook file, such as scripts or an
    empty .husky, runs no hook at all, so health still reports the stopped gates."""
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

