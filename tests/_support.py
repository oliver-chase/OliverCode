"""Helpers the tests share: loading a script as a module and building scratch git repos.

Importing this module sets GIT_CONFIG_GLOBAL=/dev/null and GIT_CONFIG_NOSYSTEM=1 for the whole
test process. A machine's global git config (a signing key, a commit template, a `core.hooksPath`,
a different default branch) would otherwise change what a scratch repo does, and a test could pass
or fail because of the machine and not the code.
"""

import importlib.util
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ISOLATION = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

os.environ.update(ISOLATION)


def git_env(**extra):
    """The environment for a git call in a scratch repo.

    Every GIT_ variable is dropped, because a suite that runs inside a hook, `git rebase -x` or
    `git bisect run` inherits GIT_DIR and GIT_INDEX_FILE, which would aim git at this checkout.
    The isolation settings come back after the drop. OLIVERCODE_SCAN_TREE goes too, so a commit
    in a scratch repo checks what it stages, even when `validate.sh --tree` started the suite.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "OLIVERCODE_SCAN_TREE"}
    env.update(ISOLATION)
    env.update(extra)
    return env


def git(repo, *args, check=True):
    """Run `git -C repo ...` in the isolated environment and return the CompletedProcess."""
    return subprocess.run(["git", "-C", str(repo), *args], env=git_env(), check=check,
                          capture_output=True, text=True)


def scratch_repo(path, *, bare=False, branch=None, identity=True):
    """Make a git repo at `path` that no machine setting can change, and return the path.

    identity=True sets a local author, so a test can commit without a global user.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    args = ["init", "-q"]
    if bare:
        args.append("--bare")
    if branch:
        args += ["-b", branch]
    git(path, *args)
    if identity and not bare:
        git(path, "config", "user.email", "test@example.invalid")
        git(path, "config", "user.name", "Test")
    return path


def load_script(relative, name=None):
    """Load a script under the repo root as a module, whether or not it ends in .py.

    scripts/ goes on sys.path first, because the scripts import `lib.*`.
    """
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    path = REPO_ROOT / relative
    name = name or path.stem.replace("-", "_")
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
