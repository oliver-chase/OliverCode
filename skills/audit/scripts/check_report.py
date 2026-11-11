#!/usr/bin/env python3
"""Check an audit report against the report rules in SKILL.md. Exit 1 and list every gap.

Usage: check_report.py REPORT.md
"""
import re
import sys

HEADINGS = ["what it is", "goal", "size today", "findings", "cuts and simplifications",
            "outcomes", "added to the board", "read and unknown", "coverage"]
LENSES = {
    "autonomy and user flow": r"autonomy|user flow",
    "self-containment": r"self-contain",
    "accuracy": r"accura",
    "one home per concept": r"one home",
    "over-engineering and unused parts": r"over-engineer|unused",
    "cost in use": r"cost in use|cost to",
    "voice": r"voice",
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


def check(text):
    problems = []
    order, parts = sections(text)
    found = [next((o for o in order if o.startswith(h)), None) for h in HEADINGS]
    for h, f in zip(HEADINGS, found):
        if f is None:
            problems.append(f"missing section: {h}. Fix: add a heading named \"{h}\"")
    present = [order.index(f) for f in found if f is not None]
    if present != sorted(present):
        problems.append("sections are out of order. Fix: use the order in SKILL.md, with Coverage last")
    if found[-1] is not None and order[-1] != found[-1]:
        problems.append("Coverage is not the last section")
    body = "\n".join(parts.get(found[3] or "", []))
    for lens, rx in LENSES.items():
        if not re.search(rx, body, re.I):
            problems.append(f"findings never mention the lens: {lens}. Fix: add a row, or \"Checked, nothing found\" with what was checked")
    for key in (found[3], found[4], found[8]):
        for row in rows_without_issue(parts.get(key or "", [])):
            problems.append(f"row with no issue number: {row[:90]}. Fix: file it and cite #number")
    cov = parts.get(found[8] or "", [])
    if found[8] and not any(ISSUE.search(l) for l in cov):
        problems.append("coverage lists no issue numbers. Fix: list every finding with its issue")
    last = "\n".join(parts.get(found[7] or "", []))
    if found[7] and not re.search(r"\bunknown\b|\bnot (checked|run|verified|done|tested)\b|\bnothing unverified\b", last, re.I):
        problems.append("read and unknown says nothing about what was not checked. Fix: state it, or \"nothing unverified\" with what was run")
    return problems


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    problems = check(open(argv[1]).read())
    for p in problems:
        print("REPORT: " + p)
    if not problems:
        print("report: complete.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
