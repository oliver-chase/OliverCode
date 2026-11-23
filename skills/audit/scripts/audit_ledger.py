#!/usr/bin/env python3
"""The audit ledger: which files an audit already read, so the next audit reads only what changed.

Usage:
    audit_ledger.py [repo] --pending            # files new or changed since the ledger, then their count, total lines and the paths gone
    audit_ledger.py [repo] --batches N          # the pending files in batches of about N lines, one batch per reader
    audit_ledger.py [repo] --mark FILE          # record the files listed in FILE (one path per line) at HEAD
    audit_ledger.py [repo] --mark FILE --findings N   # also add a run line with today's date and the finding count
    audit_ledger.py [repo] --mark-all           # record every tracked file at HEAD (after a full audit)
    audit_ledger.py [repo] --reject FILE --claim TEXT        # remember a claim a fresh reader refuted, against FILE's current hash
    audit_ledger.py [repo] --check-claim FILE --claim TEXT   # exit 1 and name the earlier rejection when FILE is unchanged since
The ledger is docs/AUDITED.txt: `# run DATE findings N files M` lines, oldest first, then one `blob-hash path`
line per file read, sorted. A file counts as read
while its blob hash is unchanged, so an edit, a rename or a new file is pending and nothing else is.
Tests: python3 -m unittest test_audit_ledger
"""

import codecs
from datetime import date
import re
import sys
from pathlib import Path

from _fleet import git, scan_root

LEDGER = "docs/AUDITED.txt"
SKIP = (LEDGER,)


def blobs(repo, rev="HEAD"):
    """{path: blob hash} for every file at `rev`."""
    out = {}
    # -z keeps a non-ASCII path as its real name; without it git prints an octal-quoted form
    # that a --mark listing of real names never matches.
    for line in git(repo, "ls-tree", "-r", "-z", rev).split("\0"):
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return {p: h for p, h in out.items() if p not in SKIP and not p.endswith((".png", ".jpg", ".ico", "package-lock.json"))}


def _unquote(path):
    """A ledger line written before ls-tree used -z may hold git's quoted form, such as "AI\\342\\200\\231s.md"."""
    if len(path) > 1 and path[0] == path[-1] == '"':
        return codecs.escape_decode(path[1:-1].encode("utf-8"))[0].decode("utf-8", errors="replace")
    return path


def read_ledger(repo):
    f = Path(repo) / LEDGER
    pairs = [l.split(" ", 1) for l in f.read_text(encoding="utf-8").splitlines() if " " in l and not l.startswith("#")] if f.exists() else []
    return {_unquote(path): h for h, path in pairs}


def run_lines(repo):
    """The ledger's `# run` lines, oldest first. They record each audit's date and finding count."""
    f = Path(repo) / LEDGER
    return [l for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("# run ")] if f.exists() else []


def _claim(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def rejections(repo):
    """[(blob, path, claim)] from the ledger's `# rejected BLOB PATH :: CLAIM` lines."""
    f = Path(repo) / LEDGER
    out = []
    for l in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        if l.startswith("# rejected ") and " :: " in l:
            head, claim = l[len("# rejected "):].split(" :: ", 1)
            blob, _, path = head.partition(" ")
            out.append((blob, path, claim))
    return out


def earlier_rejection(repo, path, claim):
    """The earlier rejection of this claim on this file, while the file's blob is unchanged, else None."""
    h = blobs(repo).get(path)
    return next((f"rejected earlier: {c} ({path})" for b, p, c in rejections(repo) if p == path and b == h and c == _claim(claim)), None)


def reject(repo, path, claim):
    """Remember a rejected claim against the file's current blob, so a later audit of the unchanged file does not refile it."""
    h = blobs(repo).get(path)
    if h is None:
        return False
    if not earlier_rejection(repo, path, claim):
        write_ledger(repo, read_ledger(repo), extra=[(h, path, _claim(claim))])
    return True


def write_ledger(repo, entries, run=None, extra=()):
    """Write the entries, keeping every earlier run line and every rejection whose file is unchanged, and appending `run` when given."""
    f = Path(repo) / LEDGER
    runs = run_lines(repo) + ([run] if run else [])
    live = blobs(repo)
    kept = [r for r in rejections(repo) + list(extra) if live.get(r[1]) == r[0]]
    kept = [r for i, r in enumerate(kept) if r not in kept[:i]]
    f.parent.mkdir(exist_ok=True)
    f.write_text("".join(f"{r}\n" for r in runs) + "".join(f"# rejected {b} {p} :: {c}\n" for b, p, c in kept)
                 + "".join(f"{h} {p}\n" for p, h in sorted(entries.items())), encoding="utf-8")


def pending(repo):
    have, now = read_ledger(repo), blobs(repo)
    return sorted(p for p, h in now.items() if have.get(p) != h)


def line_count(repo, path):
    f = Path(repo) / path
    return len(f.read_text(encoding="utf-8", errors="ignore").splitlines()) if f.is_file() else 0


def batches(repo, size):
    """The pending files as [(paths, lines)], in path order so a folder's files stay together. A batch closes
    before it passes `size` lines, and a file longer than `size` gets a batch of its own."""
    out, cur, n = [], [], 0
    for p in pending(repo):
        k = line_count(repo, p)
        if cur and n + k > size:
            out.append((cur, n))
            cur, n = [], 0
        cur.append(p)
        n += k
    if cur:
        out.append((cur, n))
    return out


def gone(repo):
    """Ledger paths no longer at HEAD. Each is named here until the next mark drops it."""
    now = blobs(repo)
    return sorted(p for p in read_ledger(repo) if p not in now)


def mark(repo, paths, rev="HEAD", findings=None, today=None):
    """Record each listed path that exists at `rev`, and return how many were recorded. With `findings`,
    also add a run line holding today's date, the finding count and the number of files read."""
    now, have, live = blobs(repo, rev), read_ledger(repo), blobs(repo)
    recorded = [p for p in paths if p in now]
    for p in recorded:
        have[p] = now[p]
    run = None
    if findings is not None:
        run = f"# run {today or date.today().isoformat()} findings {int(findings)} files {len(recorded)}"
    write_ledger(repo, {p: h for p, h in have.items() if p in live}, run)
    return len(recorded)


def main(argv):
    args = argv[1:]
    repo = scan_root([a for i, a in enumerate(args) if not (a.startswith("--") or (i and args[i - 1] in ("--mark", "--findings", "--batches", "--reject", "--check-claim", "--claim")))], Path("."))
    if "--pending" in args:
        rows = pending(repo)
        lines = sum(line_count(repo, p) for p in rows)
        print("\n".join(rows))
        total = len(blobs(repo))
        print(f"pending: {len(rows)} of {total} files, {lines} lines" + ("" if read_ledger(repo) else " (no ledger yet: a full audit)"))
        for p in gone(repo):
            print(f"gone since the audit: {p}")
        return 0
    if "--batches" in args:
        size = int(args[args.index("--batches") + 1])
        found = batches(repo, size)
        for i, (paths, n) in enumerate(found, 1):
            print(f"# batch {i}: {len(paths)} files, {n} lines")
            print("\n".join(paths))
        print(f"batches: {len(found)} of about {size} lines, {sum(len(b) for b, _ in found)} files, {sum(n for _, n in found)} lines")
        return 0
    if "--mark" in args:
        # One path per line: a path may hold spaces, such as "01 - Skills/a/SKILL.md".
        listing = [l.strip() for l in Path(args[args.index("--mark") + 1]).read_text(encoding="utf-8").splitlines() if l.strip()]
        findings = args[args.index("--findings") + 1] if "--findings" in args else None
        print(f"marked {mark(repo, listing, findings=findings)} file(s)")
        return 0
    if "--reject" in args or "--check-claim" in args:
        flag = "--reject" if "--reject" in args else "--check-claim"
        path, claim = args[args.index(flag) + 1], args[args.index("--claim") + 1] if "--claim" in args else ""
        if flag == "--reject":
            print("rejection recorded" if reject(repo, path, claim) else f"{path} is not at HEAD, nothing recorded")
            return 0
        found = earlier_rejection(repo, path, claim)
        print(found or "no earlier rejection")
        return 1 if found else 0
    if "--mark-all" in args:
        print(f"marked {mark(repo, list(blobs(repo)))} file(s)")
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
