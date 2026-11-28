#!/usr/bin/env python3
"""Leak scan: does a clone carry the owner's data? (#559)

Usage: leak_scan.py [REPO]            scan the tracked files and every reachable commit
       leak_scan.py [REPO] --release DIR   write the repo's tracked files to DIR as one commit with a neutral author, then scan DIR

The identifiers come from the repo itself: each commit author's name and email local part, the email domain when it is
not a noreply address, the owner segment of the origin remote, and the home folder of the user running the scan. The
files that must name the board (BOARD_FILES) may carry the owner's handle. The report names each file and commit and
counts hits, and never prints an identifier. Exits 1 on any hit in a tracked file outside BOARD_FILES, and 0 otherwise. Commits and author identities in
history are counted and are fixed by the single-commit release, which is scanned the same way.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import gitfiles  # noqa: E402

BOARD_FILES = ("docs/backlog-config.json", ".mailmap")  # .mailmap names the history identities it maps to one public identity
GENERIC = {"claude", "anthropic", "github", "noreply", "bot", "root", "user", "users", "test", "example"}
NEUTRAL_AUTHOR = ("OliverCode Release", "release" + chr(64) + "example.invalid")


def identifiers(repo: Path) -> list[str]:
    found: set[str] = set()
    for line in gitfiles.out(repo, "log", "--all", "--format=%an\t%ae").splitlines():
        name, _, mail = line.partition("\t")
        if "[bot]" in name.lower() or mail.lower().endswith("@anthropic.com"):
            continue
        local, _, domain = mail.lower().partition("@")
        found.update([name.lower(), local.split("+")[-1] if "noreply.github.com" in domain else local])
        if domain and "noreply" not in domain and "example" not in domain and "invalid" not in domain:
            found.add(domain)
    origin = gitfiles.out(repo, "remote", "get-url", "origin").strip()
    match = re.search(r"[:/]([^/:]+)/[^/]+?(?:\.git)?$", origin) if re.match(r"[a-z][a-z0-9+.-]*://|[^/\s]+@[^/\s]+:", origin) else None  # a local path names a folder, not an owner
    if match:
        found.add(match.group(1).lower())
    found.add(str(Path.home()).lower())
    product = {repo.resolve().name.lower(), "olivercode"}
    return sorted(i for i in found if len(i) >= 5 and i not in GENERIC and re.search(r"[a-z]", i)
                  and not any(i in q or i.startswith(q + " ") for q in product))


def _pattern(ids: list[str]):
    return re.compile("|".join(re.escape(i) for i in ids), re.I) if ids else None


def scan(repo: Path) -> dict:
    """{'files': [paths], 'commits': [short hashes], 'authors': N, 'board': [paths]} for a repo."""
    ids = identifiers(repo)
    pat = _pattern(ids)
    out = {"files": [], "board": [], "commits": [], "authors": 0}
    if not pat:
        return out
    for name in gitfiles.out(repo, "ls-files").splitlines():
        path = repo / name
        if path.is_file() and pat.search(path.read_text(encoding="utf-8", errors="ignore")):
            (out["board"] if name in BOARD_FILES else out["files"]).append(name)
    out["authors"] = len({l for l in gitfiles.out(repo, "log", "--all", "--format=%an\t%ae").splitlines()
                          if pat.search(l)})
    for entry in gitfiles.out(repo, "log", "--all", "-p", "--format=%x01%h", "--no-color").split("\x01")[1:]:
        head, _, body = entry.partition("\n")
        added = "\n".join(l for l in body.splitlines() if l.startswith("+") and not l.startswith("+++"))
        files = re.findall(r"^diff --git a/(\S+)", body, re.M)
        if pat.search(added) and not all(f in BOARD_FILES for f in files):
            out["commits"].append(head)
    return out


def release(repo: Path, dest: Path) -> Path:
    """Tracked files of `repo` as one commit with a neutral author in `dest`."""
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty, so nothing was written. Pass an empty or new folder.")
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "HEAD"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": NEUTRAL_AUTHOR[0], "GIT_AUTHOR_EMAIL": NEUTRAL_AUTHOR[1],
           "GIT_COMMITTER_NAME": NEUTRAL_AUTHOR[0], "GIT_COMMITTER_EMAIL": NEUTRAL_AUTHOR[1]}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--no-verify", "-m", "Public release"]):
        subprocess.run(["git", "-C", str(dest), *args], check=True, env=env, capture_output=True)
    return dest


def report(result: dict) -> str:
    lines = [f"{len(result['files'])} tracked file(s) carry an owner identifier outside the board files",
             *[f"  {f}" for f in result["files"]],
             f"{len(result['commits'])} commit(s) add one outside the board files",
             f"{result['authors']} author identity line(s) in history name the owner"]
    if result["board"]:
        lines.append("Files that must name the board (a fork replaces them with `olivercode backlog-setup --apply`): "
                     + ", ".join(result["board"]))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--release"]
    repo = Path(args[0] if args and not (argv[0] == "--release") else ".").resolve()
    if "--release" in argv:
        dest = Path(argv[argv.index("--release") + 1])
        repo_arg = argv[0] if argv[0] != "--release" else "."
        # the release is scanned with the identifiers of the source repo it came from
        source_ids = identifiers(Path(repo_arg).resolve())
        out = release(Path(repo_arg).resolve(), dest)
        pat = _pattern(source_ids)
        hits = [n for n in gitfiles.out(out, "ls-files").splitlines() if n not in BOARD_FILES and pat
                and pat.search((out / n).read_text(encoding="utf-8", errors="ignore"))]
        print(f"Release written to {out} as one commit with a neutral author. {len(hits)} file(s) still carry an owner identifier.")
        for h in hits:
            print(f"  {h}")
        return 1 if hits else 0
    result = scan(repo)
    print(report(result))
    return 1 if result["files"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
