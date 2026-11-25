"""The record of passing full validations, and the pre-push check that reads it.

A passing `scripts/validate.sh` run writes one line to $OLIVERCODE_HOME/validated.jsonl (default
~/.olivercode): the tree it validated, the time and exit 0. The pre-push hook refuses a push to main
whose commit has no such line younger than seven days.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from lib.failure_log import home
except ImportError:  # loaded bare, with scripts/lib on the path
    from failure_log import home

KEEP_LINES = 200
MAX_AGE = timedelta(days=7)
OVERRIDE = "OLIVERCODE_ALLOW_UNVALIDATED_PUSH"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
UNTRACKED_IGNORED = ("docs/LESSONS.jsonl",)  # a session writes these into the checkout; untracked, they never change the tree


def path() -> Path:
    return home() / "validated.jsonl"


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, text=True, check=True).stdout.strip()


def working_tree(root: Path) -> str:
    """The tree a commit of everything in the working tree (new files included, ignored files and an untracked docs/LESSONS.jsonl left out) would hold."""
    with tempfile.TemporaryDirectory(prefix="validated-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(root, "add", "-A", env=env)
        for name in UNTRACKED_IGNORED:
            if subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", name], capture_output=True).returncode != 0:
                _git(root, "rm", "--cached", "--ignore-unmatch", "-q", name, env=env)
        return _git(root, "write-tree", env=env)


def record(root: Path, tree: str | None = None, check: str = "") -> None:
    """Append one pass for `tree` (the working tree of `root` when none is given), and keep the newest 200 lines."""
    line = json.dumps({"tree": tree or working_tree(root), "time": datetime.now(timezone.utc).strftime(STAMP), "exit": 0, **({"check": check} if check else {})})
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    (home() / "launcher").write_text(str(Path(__file__).resolve().parent.parent / "olivercode") + "\n", encoding="utf-8")
    target.write_text("\n".join((lines + [line])[-KEEP_LINES:]) + "\n", encoding="utf-8")


def has_writer(root: Path) -> bool:
    script = root / "scripts" / "validate.sh"
    try:
        return "validated record" in script.read_text(encoding="utf-8")
    except OSError:
        return False


def recorded_pass(tree: str, now: datetime | None = None, check: str = "") -> dict | None:
    """The newest recent passing record for `tree` (its time and tree), or None when there is none. `check` names a separate pass, such as the drain canary's;
    a full validation has none, so a canary pass never counts as a full validation."""
    now = now or datetime.now(timezone.utc)
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
            when = datetime.strptime(row["time"], STAMP).replace(tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            continue
        if row.get("tree") == tree and row.get("exit") == 0 and row.get("check", "") == check and now - when < MAX_AGE:
            return row
    return None


def is_validated(tree: str, now: datetime | None = None) -> bool:
    return recorded_pass(tree, now) is not None


CANARY = "tests/test_drain_canary.py"


def run_canary(root: Path) -> bool:
    """Run the canary in the per-user validation queue, like every other start of the suite (the queue-bypass gate reads this line)."""
    try:
        from lib import validate_queue
    except ImportError:  # loaded bare, with scripts/lib on the path
        import validate_queue
    return validate_queue.run([sys.executable, "-m", "unittest", "discover", "-b", "-s", str(root / "tests"), "-p", "test_drain_canary.py"]) == 0


def canary(root: Path, tree: str, run=None) -> int:
    """0 when the drain canary has passed for `tree` or the repo has none. A full validation leaves it out (#1155), so the push runs it once and records the pass.
    It runs the checkout's own code, so it can only run for the tree that is checked out."""
    if not (root / CANARY).is_file() or recorded_pass(tree, check="canary"):
        return 0
    if working_tree(root) != tree:
        print(f"  BLOCKED: the drain canary has no pass for tree {tree[:12]} and the checkout holds another tree. Check out the commit, then push again.")
        return 1
    print("  Running the drain canary for this push, about 20 seconds...")
    if (run or run_canary)(root):
        record(root, tree, check="canary")
        return 0
    print(f"  BLOCKED: the drain canary failed. Run `OLIVERCODE_CANARY=1 bash scripts/validate.sh` and fix what it names. To push anyway: {OVERRIDE}=1 git push ...")
    return 1


def check(root: Path, sha: str) -> int:
    """0 when the commit's tree has a recent passing record, the repo has no writer or the override is set; else 1."""
    if not has_writer(root):
        print("  Validation record check skipped (this repo's scripts/validate.sh does not write one).")
        return 0
    try:
        tree = _git(root, "rev-parse", f"{sha}^{{tree}}")
    except subprocess.CalledProcessError:
        print(f"  Validation record check skipped ({sha[:12]} is not a commit in this repo).")
        return 0
    if is_validated(tree):
        return 0 if os.environ.get(OVERRIDE) == "1" else canary(root, tree)
    if os.environ.get(OVERRIDE) == "1":
        print(f"{OVERRIDE}=1: pushing {sha[:12]} to main without a passing validation on record.", file=sys.stderr)
        try:
            from lib import failure_log
        except ImportError:  # loaded bare, with scripts/lib on the path
            import failure_log
        failure_log.record("pre-push", f"unvalidated push allowed for {sha[:12]}", root.name)
        return 0
    print(f"  BLOCKED: tree {tree[:12]} of {sha[:12]} has no passing full validation from the last 7 days.")
    print("  Run `bash scripts/validate.sh` in this checkout with the commit checked out and let it finish with exit 0, then push again.")
    print(f"  To push anyway: {OVERRIDE}=1 git push ...")
    return 1


def command(argv: list[str]) -> int:
    """`olivercode validated snapshot | record [TREE]` (in the current repo) or `olivercode validated check SHA`."""
    try:
        root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    except (subprocess.CalledProcessError, OSError):
        print(f"Error: {Path.cwd()} is not inside a git repo. Run `olivercode validated` from a repo's folder.")
        return 1
    if argv == ["snapshot"]:
        print(working_tree(root))
        return 0
    if argv[:1] == ["record"] and len(argv) <= 2:
        record(root, argv[1] if len(argv) == 2 else None)
        return 0
    if len(argv) == 2 and argv[0] == "check":
        return check(root, argv[1])
    print("Usage: olivercode validated snapshot | record [TREE] | check SHA")
    return 1
