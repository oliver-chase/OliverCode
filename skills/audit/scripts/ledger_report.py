#!/usr/bin/env python3
"""The fleet ledger report: for every git repo under a root, whether its audit ledger is current.

Usage:
    ledger_report.py [root]     # root defaults to the folder that holds this checkout
A repo is current when every auditable file at HEAD has its blob hash in docs/AUDITED.txt, stale when some
changed since the last audit, and unaudited when it has no ledger. The last column flags uncommitted work.
Each repo that is not current is then listed with the command that scopes its audit.
Exit status is 1 when any repo is stale or unaudited. It edits nothing.
"""

import sys
from pathlib import Path

from _fleet import archived_state, git, personal_repos
from audit_ledger import LEDGER, blobs, pending, read_ledger

SKIP_DIRS = {"_archive", "_worktrees"}


def repos(root):
    """Every first-level folder of `root` that is a git work tree, by name. A repo GitHub archived or deleted, and one named in `personalRepos` of olivercode.local.json, is left out, with one line on stderr."""
    found = []
    personal = personal_repos()
    for p in sorted(Path(root).iterdir()):
        if not (p.is_dir() and p.name not in SKIP_DIRS | personal and (p / ".git").exists()):
            continue
        state = archived_state(p)
        if state:
            print(f"skip {p.name}: {state} on GitHub", file=sys.stderr)
        else:
            found.append(p)
    return found


def row(repo):
    """(name, state, pending, total, dirty) for one repo."""
    total = len(blobs(repo))
    dirty = bool(git(repo, "status", "--porcelain").strip())
    if not read_ledger(repo):
        return repo.name, "unaudited", total, total, dirty
    left = len(pending(repo))
    return repo.name, "current" if left == 0 else "stale", left, total, dirty


def next_steps(rows, root):
    """One line per repo that is not current, naming the command that scopes its audit."""
    script = Path(__file__).resolve().parent / "audit_ledger.py"
    return [f"{state:<10}  {name}: python3 {script} {Path(root) / name} --pending"
            for name, state, *_ in rows if state != "current"]


def main(argv):
    root = Path(argv[1]).expanduser() if len(argv) > 1 else Path(__file__).resolve().parents[4]
    rows = [row(r) for r in repos(root)]
    width = max((len(r[0]) for r in rows), default=4)
    print(f"{'repo':<{width}}  state       pending  files  uncommitted")
    for name, state, left, total, dirty in rows:
        print(f"{name:<{width}}  {state:<10}  {left:>7}  {total:>5}  {'yes' if dirty else 'no'}")
    behind = [r for r in rows if r[1] != "current"]
    print(f"\n{len(rows) - len(behind)} of {len(rows)} repos have a current ledger ({LEDGER}).")
    if behind:
        print("\nTo audit each one, run the audit skill on it, scoped by:")
        print("\n".join(next_steps(rows, root)))
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
