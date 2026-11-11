#!/usr/bin/env python3
"""Count the commit findings in each repo and the change since the last run. It edits no repo and writes only its state file.

Usage:
    commit_audit.py REPO [REPO ...] [--since 30.days] [--state FILE]

Each class counts commits on the current branch since --since:
    no-story       a commit that cites no #N, merges excluded
    pr-merge       a commit made by merging a pull request
    code-no-test   a commit that changes code, changes no test and gives no "No test:" reason
    coauthor-form  a Co-Authored-By line in any form but "Co-Authored-By: Name <email>"
    voice          a message line with contrast framing or a bullet that ends in a period
The last run's counts live in --state (default ~/.cache/olivercode/commit-audit.json), outside every repo.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from _fleet import is_test
from fleet_check import CONTRAST  # one contrast-framing pattern for the audit and the fleet check

STORY = re.compile(r"(^|[^\w/#&])#0*[1-9][0-9]*\b|[\w.-]+/[\w.-]+#0*[1-9][0-9]*\b")
CODE = re.compile(r"\.(py|sh|js|mjs|ts|tsx)$")
COAUTHOR_OK = re.compile(r"^Co-Authored-By: [^<>]+ <[^<>@ ]+@[^<> ]+>$")
CLASSES = ("no-story", "pr-merge", "code-no-test", "coauthor-form", "voice")
SEP, END = "\x1e", "\x1f"


def commits(repo, since):
    out = subprocess.run(["git", "-C", str(repo), "log", f"--since={since}", f"--format={SEP}%H%n%P%n%B{END}", "--name-only"],
                         capture_output=True, text=True, check=True).stdout
    for block in out.split(SEP)[1:]:
        head, _, names = block.partition(END)
        sha, parents, text = (head.split("\n", 2) + ["", ""])[:3]
        yield sha, len(parents.split()), text, [n for n in names.splitlines() if n.strip()]


def findings(repo, since):
    found = {c: [] for c in CLASSES}
    for sha, nparents, text, files in commits(repo, since):
        short, subject = sha[:7], text.strip().splitlines()[0] if text.strip() else ""
        merge = nparents > 1 or subject.startswith("Merge ")
        if subject.startswith("Merge pull request #"):
            found["pr-merge"].append(short)
        if not merge and not STORY.search(text):
            found["no-story"].append(short)
        code = [f for f in files if CODE.search(f) and not is_test(f)]
        if not merge and code and not any(is_test(f) for f in files) \
                and not re.search(r"^\s*no test:\s*\S", text, re.I | re.M):
            found["code-no-test"].append(short)
        if any(re.match(r"\s*co-authored-by:", l, re.I) and not COAUTHOR_OK.match(l) for l in text.splitlines()):
            found["coauthor-form"].append(short)
        if any(CONTRAST.search(l) or re.match(r"\s*[-*]\s+.*\.$", l) for l in text.splitlines()):
            found["voice"].append(short)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("repos", nargs="+", type=Path)
    parser.add_argument("--since", default="30.days")
    parser.add_argument("--state", type=Path, default=Path.home() / ".cache" / "olivercode" / "commit-audit.json")
    args = parser.parse_args(argv)
    try:
        last = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    now = {}
    for repo in args.repos:
        name = repo.resolve().name
        found = findings(repo, args.since)
        now[name] = {c: len(v) for c, v in found.items()}
        print(f"== {name} (since {args.since})")
        for c in CLASSES:
            before = last.get(name, {}).get(c)
            change = "first run" if before is None else f"{now[name][c] - before:+d} since last run"
            sample = " ".join(found[c][:5])
            print(f"{c}: {now[name][c]} ({change})" + (f"  e.g. {sample}" if sample else ""))
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
