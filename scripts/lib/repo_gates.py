"""Whether git will actually run a repo's commit gates.

A repo that ships `.githooks/pre-commit` is only protected while `core.hooksPath` points
at a directory holding an executable `pre-commit`. When it does not, git runs no hooks
and says nothing, so a commit with a secret in it goes straight through. The Claude Code
hooks in `scripts/hooks/` call this at session start and before every `git commit`, so
the fail-open is caught in the session that would commit, in any repo, registered or not.

Standard library only: these checks run inside a hook on every Bash call.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def repo_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def hooks_path(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def has_gates(root: Path) -> bool:
    """The repo ships its own commit gates."""
    return (root / ".githooks" / "pre-commit").is_file()


def gate_problem(root: Path) -> str:
    """Why git would skip this repo's gates, or "" when they run. Only for a repo with gates."""
    configured = hooks_path(root)
    if not configured:
        return "core.hooksPath is unset, so git runs none of this repo's commit gates"
    hooks_dir = Path(configured).expanduser()
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    if hooks_dir.resolve() != (root / ".githooks").resolve():
        # Any other folder with an executable pre-commit, such as .git/hooks or a global
        # hooks path, passes git's check while the repo's own gates never run.
        return f"core.hooksPath points at {configured}, so this repo's .githooks gates never run"
    return hooks_dir_problem(hooks_dir)


def hooks_dir_problem(hooks_dir: Path) -> str:
    """Why git would run no hook from this directory, or "" when its pre-commit runs.
    gate_problem is its one caller."""
    if not hooks_dir.is_dir():
        return f"core.hooksPath points at {hooks_dir}, which does not exist, so git runs no hooks"
    live = hooks_dir / "pre-commit"
    if not live.is_file():
        return f"{hooks_dir} holds no pre-commit file, so git runs no hooks"
    if not os.access(live, os.X_OK):
        return f"{live} is not executable, so git skips it"
    return ""


def hook_problems(repo_root: Path, templates_dir: Path, private_repo: bool) -> list[str]:
    """Return human-readable problems with a repo's live hooks, or [] when they match.

    `repo_gates.gate_problem` first catches every state where git runs none of the repo's
    gates: hooksPath unset or pointed away from `.githooks`, the folder or its pre-commit
    missing, or a pre-commit that is not executable. The live pre-commit must then match
    the one template this repo's variant names, so a public repo running the weaker private
    hook fails. pre-push and commit-msg must match their templates too, because sync-hooks deploys them.
    """
    gate = gate_problem(repo_root)
    if gate:
        return [gate]

    hooks_dir = repo_root / ".githooks"
    expected = {"pre-commit": "pre-commit-private" if private_repo else "pre-commit",
                "pre-push": "pre-push", "commit-msg": "commit-msg"}

    problems = []
    for filename, template in expected.items():
        installed = hooks_dir / filename
        canonical = templates_dir / template
        if not installed.is_file():
            problems.append(f"no {filename} in {hooks_dir}")
        elif not os.access(installed, os.X_OK):
            problems.append(f"{installed} is not executable, so git skips it")
        elif installed.read_bytes() != canonical.read_bytes():
            problems.append(f"{filename} diverges from the {template} template")

    return problems


class SizeError(Exception):
    """Why a repo's line total or baseline could not be read: `kind` is missing, invalid or count, and `detail` names what failed."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def size_allowance(baseline: dict) -> int:
    """The lines a repo may grow past its recorded baseline: allowancePercent (default 5) of "lines". The shell gate in
    core/hooks/gates/size-ratchet.sh applies the same rule."""
    return (baseline.get("lines") or 0) * baseline.get("allowancePercent", 5) // 100


def size_report(repo: Path, oc_root: Path) -> tuple[int, dict]:
    """(the repo's line total, its docs/SIZE-BASELINE.json) from the counter the size-ratchet gate uses; raises SizeError when either cannot be read."""
    path = repo / "docs" / "SIZE-BASELINE.json"
    if not path.is_file():
        raise SizeError("missing", str(path))
    try:
        baseline = json.loads(path.read_text())
    except ValueError as exc:
        raise SizeError("invalid", str(exc)) from exc
    done = subprocess.run(["bash", str(oc_root / "skills" / "audit" / "scripts" / "size.sh"), "--total", str(repo)], capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip().isdigit():
        raise SizeError("count", done.stderr.strip() or done.stdout.strip())
    return int(done.stdout), baseline
