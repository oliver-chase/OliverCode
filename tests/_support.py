"""Helpers the tests share: loading a script as a module and building scratch git repos.

Importing this module sets GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1 and OLIVERCODE_LOCAL_CONFIG=/dev/null and a temporary HOME for the whole
test process. A machine's global git config (a signing key, a commit template, a `core.hooksPath`,
a different default branch) would otherwise change what a scratch repo does, and a test could pass
or fail because of the machine and not the code.
"""

import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ISOLATION = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# olivercode.local.json lists this machine's real repos, and a command that reaches them
# (sync-hooks, health) would write there. Pointing the config at /dev/null keeps every test on scratch paths.
os.environ["OLIVERCODE_LOCAL_CONFIG"] = os.devnull

os.environ.update(ISOLATION)
# repo_state asks GitHub whether a repo is archived; no test reaches the network, so a test that wants an answer injects one.
os.environ["OLIVERCODE_ARCHIVED"] = "off"
# The session hook starts a background groom when the last one is old; no test starts one.
os.environ["OLIVERCODE_NO_BACKGROUND"] = "1"
os.environ["OLIVERCODE_NO_STARTUP_CHECK"] = "1"  # manager check skips the start-up checklist (#726); its own tests unset this

# The suite runs with a throwaway HOME, so no test can back up, relink or rewrite the owner's
# real ~/.claude. A test that needs a home of its own still sets one.
REAL_HOME = os.environ.get("HOME")
TEST_HOME = tempfile.mkdtemp(prefix="olivercode-test-home-")
atexit.register(shutil.rmtree, TEST_HOME, ignore_errors=True)
os.environ["HOME"] = TEST_HOME

# The built hooks are untracked (HOOK-OUTPUTS-1), and many tests copy or run them, so a fresh clone
# builds them before any test reads one. The build rewrites only a hook that changed.
subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build-hooks.py")], check=True)


def temp_dir(case, prefix="olivercode-test-", resolve=False):
    """A fresh temporary folder that the test case removes when it ends."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path.resolve() if resolve else path


def quiet(fn, *args, **kwargs):
    """Run fn with stdout captured; return (result, printed text)."""
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


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
    # Automatic maintenance runs in the background after a commit or push and holds locks that a copy of the repo can meet half-gone.
    git(path, "config", "maintenance.auto", "false")
    git(path, "config", "gc.auto", "0")
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


def run_hook(script, payload, env=None, raw=False):
    """Run a hook script with `payload` (a dict, or text when raw) on stdin and return the CompletedProcess."""
    import json
    return subprocess.run([sys.executable, str(script)], input=payload if raw else json.dumps(payload),
                          capture_output=True, text=True, env=env if env is not None else os.environ.copy())
