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
    from lib import gitfiles
except ImportError:  # loaded bare, with scripts/lib on the path
    import gitfiles

try:
    from lib.failure_log import home, locked, write_private
except ImportError:  # loaded bare, with scripts/lib on the path
    from failure_log import home, locked, write_private

KEEP_LINES = 200
MAX_AGE = timedelta(days=7)
OVERRIDE = "OLIVERCODE_ALLOW_UNVALIDATED_PUSH"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
UNTRACKED_IGNORED = ("docs/LESSONS.jsonl",)  # a session writes these into the checkout; untracked, they never change the tree


def path() -> Path:
    return home() / "validated.jsonl"


def working_tree(root: Path) -> str:
    """The tree a commit of everything in the working tree (new files included, ignored files and an untracked docs/LESSONS.jsonl left out) would hold."""
    with tempfile.TemporaryDirectory(prefix="validated-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        gitfiles.out(root, "add", "-A", env=env, check=True).strip()
        for name in UNTRACKED_IGNORED:
            if subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", name], capture_output=True).returncode != 0:
                gitfiles.out(root, "rm", "--cached", "--ignore-unmatch", "-q", name, env=env, check=True).strip()
        return gitfiles.out(root, "write-tree", env=env, check=True).strip()


def record(root: Path, tree: str | None = None) -> None:
    """Append one pass for `tree` (the working tree of `root` when none is given), and keep the newest 200 lines."""
    line = json.dumps({"tree": tree or working_tree(root), "time": datetime.now(timezone.utc).strftime(STAMP), "exit": 0})
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    (home() / "launcher").write_text(str(Path(__file__).resolve().parent.parent / "olivercode") + "\n", encoding="utf-8")
    with locked(target):  # held across the append and the trim, so two drains that record at once keep both rows
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) > KEEP_LINES:
            write_private(target, "\n".join(lines[-KEEP_LINES:]) + "\n")


def has_writer(root: Path) -> bool:
    script = root / "scripts" / "validate.sh"
    try:
        return "validated record" in script.read_text(encoding="utf-8")
    except OSError:
        return False


def recorded_pass(tree: str, now: datetime | None = None) -> dict | None:
    """The newest recent passing record for `tree` (its time and tree), or None when there is none."""
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
        if row.get("tree") == tree and row.get("exit") == 0 and now - when < MAX_AGE:
            return row
    return None


def is_validated(tree: str, now: datetime | None = None) -> bool:
    return recorded_pass(tree, now) is not None


def check(root: Path, sha: str) -> int:
    """0 when the commit's tree has a recent passing record, the repo has no writer or the override is set; else 1."""
    if not has_writer(root):
        print("  Validation record check skipped (this repo's scripts/validate.sh does not write one).")
        return 0
    try:
        tree = gitfiles.out(root, "rev-parse", f"{sha}^{{tree}}", check=True).strip()
    except subprocess.CalledProcessError:
        print(f"  Validation record check skipped ({sha[:12]} is not a commit in this repo).")
        return 0
    if is_validated(tree):
        return 0
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
    root = Path(gitfiles.out(Path.cwd(), "rev-parse", "--show-toplevel", check=True).strip())
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
