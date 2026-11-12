#!/usr/bin/env python3
"""The audit ledger: which files an audit already read, so the next audit reads only what changed.

Usage:
    audit_ledger.py [repo] --pending            # files new or changed since the ledger, with their lines
    audit_ledger.py [repo] --mark FILE          # record the files listed in FILE (one path per line) at HEAD
    audit_ledger.py [repo] --mark-all           # record every tracked file at HEAD (after a full audit)
    audit_ledger.py [repo] --seed SHA           # record every file as it was at SHA (an audit done earlier)
The ledger is docs/AUDITED.txt: one `blob-hash path` line per file read, sorted. A file counts as read
while its blob hash is unchanged, so an edit, a rename or a new file is pending and nothing else is.
Tests: python3 -m unittest test_audit_ledger
"""

import subprocess
import sys
from pathlib import Path

from _fleet import scan_root

LEDGER = "docs/AUDITED.txt"
SKIP = (LEDGER, "docs/CATALOG.md")


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def blobs(repo, rev="HEAD"):
    """{path: blob hash} for every file at `rev`."""
    out = {}
    for line in git(repo, "ls-tree", "-r", rev).splitlines():
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return {p: h for p, h in out.items() if p not in SKIP and not p.endswith((".png", ".jpg", ".ico", "package-lock.json"))}


def read_ledger(repo):
    f = Path(repo) / LEDGER
    pairs = [l.split(" ", 1) for l in f.read_text(encoding="utf-8").splitlines() if " " in l] if f.exists() else []
    return {path: h for h, path in pairs}


def write_ledger(repo, entries):
    f = Path(repo) / LEDGER
    f.parent.mkdir(exist_ok=True)
    f.write_text("".join(f"{h} {p}\n" for p, h in sorted(entries.items())), encoding="utf-8")


def pending(repo):
    have, now = read_ledger(repo), blobs(repo)
    return sorted(p for p, h in now.items() if have.get(p) != h)


def mark(repo, paths, rev="HEAD"):
    now, have = blobs(repo, rev), read_ledger(repo)
    for p in paths:
        if p in now:
            have[p] = now[p]
    write_ledger(repo, {p: h for p, h in have.items() if p in blobs(repo)})
    return len(paths)


def main(argv):
    args = argv[1:]
    repo = scan_root([a for i, a in enumerate(args) if not (a.startswith("--") or (i and args[i - 1] in ("--mark", "--seed")))], Path("."))
    if "--pending" in args:
        rows = pending(repo)
        lines = sum(len((Path(repo) / p).read_text(encoding="utf-8", errors="ignore").splitlines()) for p in rows if (Path(repo) / p).is_file())
        print("\n".join(rows))
        total = len(blobs(repo))
        print(f"pending: {len(rows)} of {total} files, {lines} lines" + ("" if read_ledger(repo) else " (no ledger yet: a full audit)"))
        return 0
    if "--mark" in args:
        listing = Path(args[args.index("--mark") + 1]).read_text(encoding="utf-8").split()
        print(f"marked {mark(repo, listing)} file(s)")
        return 0
    if "--mark-all" in args:
        print(f"marked {mark(repo, list(blobs(repo)))} file(s)")
        return 0
    if "--seed" in args:
        rev = args[args.index("--seed") + 1]
        write_ledger(repo, {p: h for p, h in blobs(repo, rev).items() if p in blobs(repo)})
        print(f"seeded from {rev}")
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
