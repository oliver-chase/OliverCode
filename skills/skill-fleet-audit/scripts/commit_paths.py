#!/usr/bin/env python3
"""Commit only the named paths in a tree that other Claude sessions share (SESSION-COMMIT-1).

    python3 commit_paths.py <message-file> <path-list-file> [--push] [--wait SECONDS]

The path list holds one path per line, relative to the repo root. The script waits for `.git/index.lock`,
runs `git add` on each path that exists on disk, then commits with `git commit --only` so a peer's staged
files stay out. A path that is deleted on disk is not added, because `git add` fails on a deletion that is
already staged. `--only` still commits the deletion. On a hook failure it prints only the blocked gates.
`--push` pushes after a good commit. Exit 0 on a commit, 1 on a hook block, 2 on a lock that outlasts `--wait`.
For the checks alone, without a commit, run `precheck.py`.
Tests: python3 -m unittest test_commit_tools   (from this folder)
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def read_paths(path_list):
    return [line.strip() for line in Path(path_list).read_text(encoding="utf-8").splitlines() if line.strip()]


def wait_for_lock(repo, seconds):
    lock = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "index.lock"
    deadline = time.monotonic() + seconds
    while lock.exists():
        if time.monotonic() > deadline:
            return False
        time.sleep(1)
    return True


def blocked_gates(output):
    """The `[BLOCKED]` gate sections of a hook's output, with each section's indented findings."""
    lines, keep = output.splitlines(), []
    for i, line in enumerate(lines):
        if "[BLOCKED]" in line:
            keep.append(line)
            keep += [x for x in lines[i + 1:i + 12] if x.startswith("    ")]
    return keep


def commit(repo, message_file, path_list, wait=120):
    """Return (exit code, text to print)."""
    repo = Path(repo)
    if not wait_for_lock(repo, wait):
        return 2, f"error: .git/index.lock still present after {wait}s. A git command is running. Retry later."
    paths = read_paths(path_list)
    for p in paths:
        if (repo / p).exists():
            r = git(repo, "add", "--", p)
            if r.returncode:
                return 1, f"error: git add {p}: {r.stderr.strip()}"
    r = git(repo, "commit", "--only", "--pathspec-from-file=" + str(path_list), "-F", str(message_file))
    if r.returncode:
        text = "\n".join(blocked_gates(r.stdout + r.stderr)) or (r.stderr.strip() or r.stdout.strip())
        return 1, text
    return 0, git(repo, "log", "--oneline", "-1").stdout.strip()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("message_file")
    ap.add_argument("path_list")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--wait", type=int, default=120)
    a = ap.parse_args(argv)
    top = git(".", "rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        sys.exit("error: not a git repository")
    code, text = commit(top, Path(a.message_file).resolve(), Path(a.path_list).resolve(), a.wait)
    print(text)
    if code == 0 and a.push:
        r = git(top, "push", "origin", "HEAD")
        print((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "pushed")
        code = r.returncode
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
