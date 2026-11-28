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
import sys
from pathlib import Path
try:
    from lib import gitfiles
except ImportError:  # loaded bare, with scripts/lib on the path
    import gitfiles


def hook_templates(oc_root: Path) -> Path:
    """core/templates/project with its hooks freshly built. The built hooks are untracked
    (HOOK-OUTPUTS-1), so every reader builds them first. A checkout with no builder is used as it is."""
    builder = oc_root / "scripts" / "build-hooks.py"
    if builder.is_file():
        built = subprocess.run([sys.executable, str(builder)], capture_output=True, text=True)
        if built.returncode:
            print(f"hook build failed ({(built.stderr or built.stdout).strip().splitlines()[-1:] or ['no output']}); using the templates as they are", file=sys.stderr)
    return oc_root / "core" / "templates" / "project"


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
    # lexists: a dangling link is a gate that is broken, which gate_problem names, and no gate at all would hide it.
    hook = root / ".githooks" / "pre-commit"
    return hook.is_file() or os.path.lexists(hook)


def fix_command(root: Path) -> str:
    """The command that makes git run this checkout's gates. A linked worktree needs its own setting, which plain `git config` does not give it (#786)."""
    if (root / ".git").is_file():
        return f'olivercode worktree fix "{root}"'
    return f'git -C "{root}" config core.hooksPath .githooks'


def gate_problem(root: Path) -> str:
    """Why git would skip this repo's gates, or "" when they run. Only for a repo with gates."""
    configured = hooks_path(root)
    if not configured:
        return "core.hooksPath is unset, so git runs none of this repo's commit gates"
    hooks_dir = Path(configured).expanduser()
    if hooks_dir.is_absolute() and has_gates(root):
        # Absolute works in the main checkout but sends every worktree to this checkout's hooks, where commit_guard refuses its commits.
        return f"core.hooksPath is the absolute path {configured}; set it to the relative .githooks so every worktree runs its own gates"
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    if hooks_dir.resolve() != (root / ".githooks").resolve():
        # Any other folder with an executable pre-commit, such as .git/hooks or a global
        # hooks path, passes git's check while the repo's own gates never run.
        return f"core.hooksPath points at {configured}, so this repo's .githooks gates never run"
    if not hooks_dir.is_dir():
        return f"core.hooksPath points at {hooks_dir}, which does not exist, so git runs no hooks"
    live = hooks_dir / "pre-commit"
    if not live.is_file():
        return f"{hooks_dir} holds no pre-commit file, so git runs no hooks"
    if not os.access(live, os.X_OK):
        return f"{live} is not executable, so git skips it"
    return ""


def _tracked(repo_root: Path, filename: str) -> bool:
    return gitfiles.run(repo_root, "ls-files", "--error-unmatch", f".githooks/{filename}", text=False).returncode == 0


def _committed_bytes(repo_root: Path, installed: Path, filename: str) -> bytes:
    """The hook as HEAD holds it, which is what every clone gets; an untracked hook is read from disk."""
    if _tracked(repo_root, filename):
        shown = gitfiles.run(repo_root, "show", f"HEAD:.githooks/{filename}", text=False)
        return shown.stdout if shown.returncode == 0 else b""
    return installed.read_bytes()


def hook_problems(repo_root: Path, templates_dir: Path, private_repo: bool, committed: bool = True) -> list[str]:
    """Return human-readable problems with a repo's live hooks, or [] when they match.

    `repo_gates.gate_problem` first catches every state where git runs none of the repo's
    gates: hooksPath unset or pointed away from `.githooks`, the folder or its pre-commit
    missing, or a pre-commit that is not executable. The live pre-commit must then match
    the one template this repo's variant names, so a public repo running the weaker private
    hook fails. pre-push and commit-msg must match their templates too, because sync-hooks deploys them.
    With `committed` off, only the files git runs are compared, whatever HEAD holds.
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
        elif committed and _tracked(repo_root, filename) and gitfiles.run(repo_root, "status", "--porcelain", "--", f".githooks/{filename}", text=False).stdout.strip():
            problems.append(f"{filename} is tracked but differs from HEAD, so it is hand-edited or uncommitted")
        elif (_committed_bytes(repo_root, installed, filename) if committed else installed.read_bytes()) != canonical.read_bytes():
            problems.append(f"{filename} diverges from the {template} template")

    return problems
