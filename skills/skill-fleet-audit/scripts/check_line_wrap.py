#!/usr/bin/env python3
"""One line per paragraph in skill markdown (PROSE-WRAP-1).

A paragraph written as several source lines shows as short, uneven rows in an editor such as
Obsidian's Live Preview. Write one line per paragraph and let the viewer wrap it.

Usage:
    check_line_wrap.py                 # list every markdown file under the fleet root that reflow would change
    check_line_wrap.py <path-or-dir>   # list one folder or file
    check_line_wrap.py --fix <path>    # one line per paragraph, in place
    check_line_wrap.py --blocking <file> ...   # commit gate: exit 1 on a hard-wrapped file
Tests: python3 -m unittest test_check_line_wrap   (from this scripts/ folder)
"""

import os
import re
import sys
from pathlib import Path

import _fleet
from _fleet import NON_SKILL_DIRS

SKILLS_ROOT = _fleet.FLEET_ROOT


def find_markdown_files(root):
    if root.is_file():
        return [root]
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in NON_SKILL_DIRS and not d.startswith(".")]
        for f in filenames:
            if f.endswith(".md"):
                files.append(Path(dirpath) / f)
    return sorted(files)


LIST_MARKER_RE = re.compile(r"^([-*]|\d+[.)])\s")
QUOTE_PREFIX_RE = re.compile(r"^>\s?")


def _unquote(line):
    """Strip one leading blockquote marker. A quoted line follows the same block rules as any
    other line, so a bare `>` is a paragraph break and `> - item` is a list item."""
    return QUOTE_PREFIX_RE.sub("", line, count=1)


def _is_list_line(line):
    """A markdown list item (bulleted or numbered), at any indent level, quote-prefixed or
    not. Consecutive list items are a real list, not a hard-wrapped paragraph -- each line
    is its own item on purpose, not an accidental mid-sentence break."""
    return bool(LIST_MARKER_RE.match(_unquote(line).lstrip()))


FIELD_RE = re.compile(r"^[A-Z][A-Za-z0-9 /()'&-]{0,40}: \S")


def _joinable(cur, nxt):
    """True when `nxt` continues the paragraph `cur` started. A new list item, a table row,
    a hard break (two trailing spaces or a backslash), a bold-label line after a finished
    sentence and a second `Key: value` line each start a new line on purpose."""
    c, n = _unquote(cur).rstrip("\n"), _unquote(nxt).strip()
    if c.endswith("  ") or c.endswith("\\"):
        return False
    if _is_list_line(nxt) or n.startswith("|") or c.lstrip().startswith("|"):
        return False
    if n.startswith("**") and re.search(r"[.!?:]$", c.rstrip()):
        return False
    if FIELD_RE.match(c.lstrip()) and FIELD_RE.match(n):
        return False  # two `Key: value` lines are two records, read by script or by eye
    return True


def reflow(text):
    """One line per paragraph (and per list item). Returns the new text. Fenced code,
    front matter, tables, headings, rules and comments are left as written."""
    lines = text.split("\n")
    out = []
    in_fence = in_frontmatter = False
    prev_prose = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        uq = _unquote(line).strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            out.append(line)
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            out.append(line)
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            prev_prose = False
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if (not uq or uq.startswith("#") or re.fullmatch(r"[-*_]{3,}", uq)
                or (uq.startswith("<!--") and uq.endswith("-->"))):
            prev_prose = False
            out.append(line)
            continue
        if prev_prose and _joinable(out[-1], line):
            out[-1] = out[-1].rstrip() + " " + _unquote(line).strip()
            continue
        out.append(line)
        prev_prose = not uq.startswith("|")
    return "\n".join(out)


def blocking(paths):
    """The commit gate (PROSE-WRAP-1). Fails when a given markdown file holds a hard-wrapped
    paragraph. It reads the files it is given, so a reference copy and a doc are checked too."""
    bad = []
    for p in paths:
        path = Path(p)
        if path.suffix != ".md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if reflow(text) != text:
            bad.append(p)
    if not bad:
        return 0
    print(f"{len(bad)} markdown file(s) hold a hard-wrapped paragraph. Write one line per paragraph.")
    for p in bad:
        print(f"  {p}")
    print("Fix: python3 skill-fleet-audit/scripts/check_line_wrap.py --fix <file>")
    return 1


def main(argv=None):
    global SKILLS_ROOT
    args = sys.argv[1:] if argv is None else argv
    if "--blocking" in args:
        sys.exit(blocking([a for a in args if not a.startswith("--")]))
    root = SKILLS_ROOT = _fleet.scan_root(args, SKILLS_ROOT)
    files = find_markdown_files(root)
    if "--fix" in args:
        changed = 0
        for f in files:
            text = f.read_text(encoding="utf-8")
            new = reflow(text)
            if new != text:
                f.write_text(new, encoding="utf-8")
                changed += 1
        print(f"Reflowed {changed} of {len(files)} file(s).")
        return
    wrapped = [f for f in files if reflow(f.read_text(encoding="utf-8")) != f.read_text(encoding="utf-8")]
    print(f"Scanned {len(files)} markdown file(s) under {root}.")
    if not wrapped:
        print("No hard-wrapped paragraphs found.")
        return
    print(f"-- {len(wrapped)} file(s) hold a hard-wrapped paragraph. Fix with --fix. --")
    for f in wrapped:
        print(f"  {f.relative_to(root) if root.is_dir() else f}")


if __name__ == "__main__":
    main()
