#!/usr/bin/env python3
"""Run every commit gate on a path list and print all findings at once, with no commit.

    python3 precheck.py <path-list-file>

The path list holds one path per line, relative to the repo root. The script builds a private index from
HEAD plus those paths, then runs the repo's `.githooks/pre-commit` against it. That is the same hook a commit
runs, shared gates and `pre-commit.local` together, so one pass lists every violation. Your real index and
every peer's staged file stay as they were.
A gate that scans the whole tree can fail on a peer's unfinished file. The summary says which blocked
gates name none of your paths, so you wait instead of editing the peer's file.
Exit 0 when every gate passes, 1 when one blocks.
Tests: python3 -m unittest test_commit_tools   (from this folder)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from commit_paths import blocked_gates, read_paths


def run(repo, path_list):
    """Return (exit code, output text, [blocked gate lines that name none of the paths])."""
    paths = read_paths(path_list)
    hook = Path(repo) / ".githooks" / "pre-commit"
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, VAULT_ALLOW_PLAIN_COMMIT="1", GIT_INDEX_FILE=str(Path(tmp) / "index"))
        for args in (["read-tree", "HEAD"], ["add", "--ignore-errors", "--"] + [p for p in paths if (Path(repo) / p).exists()],
                     ["rm", "-q", "--cached", "--ignore-unmatch", "--"] + [p for p in paths if not (Path(repo) / p).exists()]):
            subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True)
        r = subprocess.run(["bash", str(hook)], cwd=repo, env=env, capture_output=True, text=True)
    output = r.stdout + r.stderr
    peer = []
    section = []
    for line in blocked_gates(output) + ["[BLOCKED] end"]:
        if "[BLOCKED]" in line:
            if section and not any(p in "\n".join(section) for p in paths):
                peer.append(section[0].strip())
            section = [line]
        else:
            section.append(line)
    return r.returncode, output, peer


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    code, output, peer = run(top, argv[0])
    print(output.rstrip())
    if peer:
        print("\nBlocked gates that name none of your paths (likely a peer's unfinished work; wait and rerun):")
        print("\n".join("  " + p for p in peer))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
