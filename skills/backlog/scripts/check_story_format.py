#!/usr/bin/env python3
"""Check that an issue body follows references/story-template.md.

Usage: check_story_format.py [BODY_FILE|-] [--kind story|epic]
Reads the body from BODY_FILE, or from stdin when the file is omitted or "-". Prints each
missing part with its fix and exits 1 when any part is missing, 0 when the body is complete,
2 on a usage error. Offline: reads only the body it is given.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

STORY_SENTENCE = re.compile(r"\bAs (?:the|an?)\s+[^,\n]+?,?\s+I want\s+.+?,\s*so that\s+\S", re.I | re.S)
EPIC_LINE = re.compile(r"^\s*Epic:\s*(?:[\w.-]+/[\w.-]+)?#\d+\s*$", re.M)
PRIORITY = re.compile(r"\bPriority:\s*(\S+?)[.,;\s]", re.I)
SIZE = re.compile(r"\bSize:\s*(\S+?)[.,;\s]", re.I)
WORK_TYPE = re.compile(r"\bWork type:\s*(\w+)", re.I)
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z /|-]*>")
COVERAGE_LINE = re.compile(r"^\s*(?:[-*]\s*)?Existing coverage checked:\s*\S", re.I | re.M)
STEP = re.compile(r"^\s*(Given|When|Then|And|But)\b", re.I)
AREA = re.compile(r"^\W*Files area:\W*(.+)$", re.I | re.M)

PRIORITIES = ("P0", "P1", "P2")
SIZES = ("XS", "S", "M", "L", "XL")
WORK_TYPES = ("Story", "Epic")

TEMPLATE = "references/story-template.md"


def gherkin_problems(body):
    """Return problems with the Feature and Scenario blocks, each as (part, fix)."""
    lines = body.splitlines()
    if not any(re.match(r"^\s*Feature:\s*\S", l) for l in lines):
        return [("Gherkin Feature", "add a `Feature: <name>` line inside a ```gherkin fence, as in " + TEMPLATE)]
    scenarios, current = [], None
    for line in lines:
        m = re.match(r"^\s*Scenario(?: Outline)?:\s*(.*)$", line)
        if m:
            current = {"name": m.group(1).strip() or "(unnamed)", "steps": []}
            scenarios.append(current)
            continue
        s = STEP.match(line)
        if s and current is not None:
            current["steps"].append(s.group(1).title())
    if not scenarios:
        return [("Gherkin Scenario", "add at least one `Scenario: <name>` with Given, When and Then lines")]
    problems = []
    for sc in scenarios:
        kinds = [k for k in sc["steps"] if k in ("Given", "When", "Then")]
        missing = [k for k in ("Given", "When", "Then") if k not in kinds]
        if missing:
            problems.append((f"Scenario \"{sc['name']}\" lacks {', '.join(missing)}",
                             f"give every scenario a Given, a When and a Then line"))
        elif kinds.index("Given") > kinds.index("When") or kinds.index("When") > kinds.index("Then"):
            problems.append((f"Scenario \"{sc['name']}\" steps are out of order",
                             "write the steps in the order Given, When, Then"))
    return problems


def check_body(body, kind=None, coverage=True, root=None):
    """Return a list of (missing part, fix) for the body. An empty list means it is complete.

    `coverage=False` skips the Existing coverage checked line, for a scan of stories filed before it was required.
    `root` is the repo the story changes, so a Files area entry that is a folder there is named.
    """
    problems = []
    wt = WORK_TYPE.search(body)
    work_type = wt.group(1).capitalize() if wt else None
    kind = (kind or (work_type or "Story")).capitalize()

    if not STORY_SENTENCE.search(body.replace("*", "")):
        problems.append(("User story sentence",
                         "start with `**As the <role>**, I want <the ask>, so that <the outcome>.`"))
    problems += gherkin_problems(body)
    if kind == "Story" and not EPIC_LINE.search(body):
        problems.append(("Epic link", "add a line `Epic: #<number>` naming the epic this story belongs to; "
                                      "pick or create one first"))
    if coverage and kind == "Story" and not COVERAGE_LINE.search(body):
        problems.append(("Existing coverage checked line",
                         "add `Existing coverage checked:` naming the code, doc or issue you searched and what you found, as in " + TEMPLATE))
    p = PRIORITY.search(body + " ")
    if not p:
        problems.append(("Priority", "add `Priority: P0`, `P1` or `P2`"))
    elif p.group(1).upper() not in PRIORITIES:
        problems.append((f"Priority \"{p.group(1)}\" is not valid", "use P0, P1 or P2"))
    s = SIZE.search(body + " ")
    if not s:
        problems.append(("Size", "add `Size: XS`, `S`, `M`, `L` or `XL`"))
    elif s.group(1).upper() not in SIZES:
        problems.append((f"Size \"{s.group(1)}\" is not valid", "use XS, S, M, L or XL"))
    if not wt:
        problems.append(("Work type", "add `Work type: Story` or `Work type: Epic`"))
    elif work_type not in WORK_TYPES:
        problems.append((f"Work type \"{wt.group(1)}\" is not valid", "use Story or Epic"))
    elif work_type != kind:
        problems.append((f"Work type is {work_type} but this body is checked as a {kind.lower()}",
                         f"set `Work type: {kind}`"))
    area = AREA.search(body)
    for entry in [t.strip("`.,;*()") for t in re.split(r"[,;\s]+", area.group(1))] if area else []:
        if entry and (entry.endswith("/") or (root is not None and (Path(root) / entry).is_dir())):
            problems.append((f"Files area names the folder {entry}",
                             "name the files the story changes, because a folder holds back every story that touches a file inside it"))
    ph = PLACEHOLDER.search(re.sub(r"`[^`]*`", "", body))
    if ph:
        problems.append((f"Unfilled placeholder {ph.group(0)}", "replace every <...> with the real text"))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("body_file", nargs="?", default="-", help="issue body file, or - for stdin")
    ap.add_argument("--kind", choices=("story", "epic"), help="check as this kind; default reads Work type")
    args = ap.parse_args(argv)
    try:
        body = sys.stdin.read() if args.body_file == "-" else open(args.body_file, encoding="utf-8").read()
    except OSError as e:
        print(f"Cannot read the body: {e}", file=sys.stderr)
        return 2
    if not body.strip():
        print("The body is empty. Write it from " + TEMPLATE + ".", file=sys.stderr)
        return 1
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    problems = check_body(body, args.kind, root=(top.stdout.strip() or None) if top.returncode == 0 else None)
    for part, fix in problems:
        print(f"MISSING {part}. Fix: {fix}")
    if problems:
        return 1
    print("Story format complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
