#!/usr/bin/env python3
"""Flags a `#N` issue citation in skill content that does not resolve to a real GitHub
issue. A cited number that was never filed, or that belongs to an unrelated issue, points the
reader at the wrong work and nothing notices.

Scans `.md`, `.py`, and `.js` files under the fleet root. A citation is `#` followed by 2-4
digits, not preceded by a word character, `&`, or `/`, and not followed by a word
character. Each distinct number is looked up once with `gh api`, in the GitHub repo named by the
`SKILL_FLEET_ISSUE_REPO` environment variable (`owner/name`).

Usage:
  check_issue_refs.py            Scan the whole fleet.
  check_issue_refs.py --staged   Scan only staged files (for a commit hook).
  check_issue_refs.py PATH...    Scan the given files or folders.

Exit 1 when any citation does not resolve. Exit 0 and a note when `gh` is missing or no repo is
named, so a machine without them is never blocked. Never fixes anything: whether the wrong number is a
typo or an unfiled item is a human call.
"""
import os
import re
import subprocess
import sys

import _fleet

REPO_ENV = "SKILL_FLEET_ISSUE_REPO"
CITE = re.compile(r"(?<![\w&/#])#(\d{2,4})(?![\w-])")
EXTS = (".md", ".py", ".js")


def citations(text):
    """[(line number, issue number)] for every citation in `text`."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in CITE.finditer(line):
            out.append((i, int(m.group(1))))
    return out


def files_under(paths):
    for p in paths:
        if os.path.isfile(p):
            if p.endswith(EXTS):
                yield p
            continue
        for root, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]  # a peer's .pytest_cache comes and goes mid-scan
            if "node_modules" in root:
                continue
            for n in names:
                if n.endswith(EXTS):
                    yield os.path.join(root, n)


def staged_files(root):
    out = subprocess.run(["git", "-C", root, "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         capture_output=True, text=True).stdout.splitlines()
    return [os.path.join(root, f) for f in out if f.endswith(EXTS)]


def exists(number, cache, repo):
    if number not in cache:
        cache[number] = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".number"],
                                       capture_output=True, text=True).returncode == 0
    return cache[number]


def main():
    args = sys.argv[1:]
    root = str(_fleet.FLEET_ROOT)
    repo = os.environ.get(REPO_ENV)
    if not repo:
        print(f"{REPO_ENV} is not set -- issue citations not checked.")
        return 0
    if "--staged" in args:
        files = staged_files(root)
    elif args:
        files = list(files_under(args))
    else:
        files = list(files_under([root]))
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("gh not available -- issue citations not checked.")
        return 0
    cache, bad = {}, []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except FileNotFoundError:  # deleted between listing and reading
            continue
        for line, n in citations(text):
            if not exists(n, cache, repo):
                bad.append((os.path.relpath(f, root), line, n))
    for rel, line, n in bad:
        print(f"{rel}:{line}: #{n} is not an issue in {repo}")
    print(f"{len(files)} file(s), {len(cache)} distinct citation(s), {len(bad)} unresolved.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
