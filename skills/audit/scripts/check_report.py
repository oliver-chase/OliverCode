#!/usr/bin/env python3
"""Check an audit report against the report rules in SKILL.md. Exit 1 and list every gap.

Usage: <report> | check_report.py - [--repo DIR]
The report arrives on stdin. With --repo, a whole-repo report also fails while the audit ledger lists any file as pending. A file path fails the check, since the report is one message in the thread and never a file.
"""
import re
import sys

import audit_ledger

HEADINGS = ["what it is", "goal", "size today", "findings", "cuts and simplifications",
            "outcomes", "added to the board", "read and unknown", "coverage", "engine parts to cut or merge"]
LENSES = {
    "autonomy and user flow": r"autonomy|user flow",
    "self-containment": r"self-contain",
    "accuracy": r"accura",
    "one home per concept": r"one home",
    "over-engineering and unused parts": r"over-engineer|unused",
    "cost in use": r"cost in use|cost to",
    "voice": r"voice",
    "documentation coverage": r"documentation|doc coverage",
    "functionality gaps": r"gap",
    "portability and sharing": r"portab|sharing|shareable",
    "test necessity": r"test necessity",
}
ISSUE = re.compile(r"#\d+")
SEPARATOR = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")


def sections(text):
    parts, name = {}, None
    order = []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s*(?:\d+\.\s*)?(.+?)\.?\s*$", line)
        if m:
            name = m.group(1).strip().lower()
            order.append(name)
            parts[name] = []
        elif name is not None:
            parts[name].append(line)
    return order, parts


def rows_without_issue(lines):
    bad = []
    for i, line in enumerate(lines):
        s = line.strip()
        is_row = s.startswith("|") or re.match(r"^[-*] ", s)
        if not is_row or SEPARATOR.match(s):
            continue
        if i + 1 < len(lines) and SEPARATOR.match(lines[i + 1].strip()):
            continue  # a table header
        if ISSUE.search(s) or "nothing found" in s.lower():
            continue
        bad.append(s)
    return bad


def why_problems(lines):
    """Stories in the first table of the board section that have no Why cell, or an empty one."""
    rows = [l.strip() for l in lines if l.strip().startswith("|")]
    if len(rows) < 2 or not SEPARATOR.match(rows[1]):
        return []
    cells = lambda r: [c.strip() for c in r.strip("|").split("|")]
    head = [c.lower() for c in cells(rows[0])]
    col = head.index("why") if "why" in head else None
    out = []
    for row in rows[2:]:
        c = cells(row)
        story = next((x for x in c if ISSUE.search(x)), c[0])
        if col is None:
            out.append(f"board table has no Why column, so story {story[:40]} has no Why. Fix: add a Why column with the finding in one sentence")
        elif col >= len(c) or not c[col]:
            out.append(f"story {story[:40]} has an empty Why. Fix: write the finding in one sentence")
    return out


def check(text):
    problems = []
    order, parts = sections(text)
    found = [next((o for o in order if o.startswith(h)), None) for h in HEADINGS]
    for h, f in zip(HEADINGS, found):
        if f is None:
            problems.append(f"missing section: {h}. Fix: add a heading named \"{h}\"")
    present = [order.index(f) for f in found if f is not None]
    if present != sorted(present):
        problems.append("sections are out of order. Fix: use the order in SKILL.md, with Engine parts to cut or merge last")
    if found[-1] is not None and order[-1] != found[-1]:
        problems.append(f"{HEADINGS[-1]} is not the last section")
    # A lens counts when a finding row or a "Checked" line names it in its first cell or leading words, so a
    # passing mention deep inside an unrelated row does not satisfy it.
    body = "\n".join(l.strip("| ").split("|")[0] if l.lstrip().startswith("|") else l[:80]
                     for l in parts.get(found[3] or "", []))
    for lens, rx in LENSES.items():
        if not re.search(rx, body, re.I):
            problems.append(f"findings never mention the lens: {lens}. Fix: add a row, or \"Checked, nothing found\" with what was checked")
    for key in (found[3], found[4], found[8], found[9]):
        for row in rows_without_issue(parts.get(key or "", [])):
            problems.append(f"row with no issue number: {row[:90]}. Fix: file it and cite #number")
    problems.extend(why_problems(parts.get(found[6] or "", [])))
    cov = parts.get(found[8] or "", [])
    if found[8] and not any(ISSUE.search(l) for l in cov):
        problems.append("coverage lists no issue numbers. Fix: list every finding with its issue")
    last = "\n".join(parts.get(found[7] or "", []))
    if found[7] and not re.search(r"\bunknown\b|\bnot (checked|run|verified|done|tested)\b|\bnothing unverified\b", last, re.I):
        problems.append("read and unknown says nothing about what was not checked. Fix: state it, or \"nothing unverified\" with what was run")
    return problems


def unread(repo):
    """The coverage gate: a whole-repo report goes out only once the ledger lists nothing as pending."""
    rows = audit_ledger.pending(repo)
    if not rows:
        return []
    lines = sum(audit_ledger.line_count(repo, p) for p in rows)
    return [f"{len(rows)} files ({lines} lines) in {repo} are still unread. Fix: run the next reader wave from `audit_ledger.py --batches 3000`, mark each batch, and report when --pending lists nothing"]


def main(argv):
    repo = None
    if "--repo" in argv:
        i = argv.index("--repo")
        repo, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    if argv[1] != "-":
        print("REPORT: the report was delivered as a file. Fix: pipe it on stdin with `check_report.py -` and print it as one message in the thread")
        return 1
    problems = check(sys.stdin.read()) + (unread(repo) if repo else [])
    for p in problems:
        print("REPORT: " + p)
    if not problems:
        print("report: complete.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
