#!/usr/bin/env python3
"""Flags a plan-doc or backlog-shaped file, a citation of the old backlog ID scheme, and history
language in skill prose. GitHub Issues are the only backlog, plan and changelog store.

Three checks, run together. Each failure blocks:

1. Banned file shape. A path matching `docs/plans/*.md`, `docs/specs/*.md`, `*execution-backlog*.md`
   or `*_BACKLOG.md` (any case). That content belongs in the GitHub Project as an issue.
2. SPEC-N citation. The old backlog ID scheme is gone. The real GitHub issue number is the only
   citation.
3. History language in skill prose (SKILL-HISTORY-1). `SKILL.md` and `references/*.md` state
   what the skill does now. They hold no ISO date, no `#N` or `issue #N` id and none of the history
   words below. The reason behind a rule belongs in the family's `DECISIONS.md`, which this check
   skips. A line that needs one of these for real (test data, quoted rule text) ends with
   `<!-- allow-history -->`.

Never fixes anything.

Usage:
    check_plan_doc_leak.py                 # scan the whole fleet
    check_plan_doc_leak.py <path-or-dir>   # scan one folder
Tests: python3 -m unittest test_check_plan_doc_leak   (from this scripts/ folder)
"""

import re
import sys

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT

BANNED_PATH_PATTERNS = (
    re.compile(r"docs/plans/.*\.md$", re.IGNORECASE),
    re.compile(r"docs/specs/.*\.md$", re.IGNORECASE),
    re.compile(r"execution-backlog.*\.md$", re.IGNORECASE),
    re.compile(r"(^|/)_?backlog\.md$", re.IGNORECASE),
)
SPEC_ID_PATTERN = re.compile(r"\bSPEC-\d+\b")
HISTORY_WORDS = re.compile(
    r"\b(legacy|formerly|renamed|previously|superseded|deprecated|moved from|no longer"
    r"|confirmed (?:live|by the user))\b", re.IGNORECASE  # allow-history
)
ISO_DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
ISSUE_ID = re.compile(r"\bissue\s*#\d+|(?<![\w&])#\d{2,4}\b", re.IGNORECASE)
ALLOW_MARKER = "allow-history"


def rel_of(root, path):
    return str(path.relative_to(root.parent)).replace("\\", "/")


def is_skill_prose(rel_parts, name):
    """SKILL.md anywhere, or a references/*.md file. DECISIONS.md, README.md, docs/ and the
    packager's dist/ are out of scope."""
    if name in ("DECISIONS.md", "README.md"):
        return False
    if "docs" in rel_parts or "dist" in rel_parts or ".claude" in rel_parts:
        return False
    return name == "SKILL.md" or "references" in rel_parts


def check_history_language(root):
    findings = []
    for path in sorted(root.rglob("*.md")):
        if not is_skill_prose(path.relative_to(root).parts, path.name):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            hit = ISO_DATE.search(line) or ISSUE_ID.search(line) or HISTORY_WORDS.search(line)
            if hit:
                findings.append(f"{rel_of(root, path)}:{lineno} -- history language '{hit.group(0)}'. State what "
                                f"the skill does now; move the reason to DECISIONS.md.")
    return findings


def check_banned_paths(root):
    findings = []
    for path in root.rglob("*.md"):
        rel = rel_of(root, path)
        if any(p.search(rel) for p in BANNED_PATH_PATTERNS):
            findings.append(f"{rel} -- plan-doc/backlog-shaped file path. Migrate its content into a "
                            f"GitHub issue (Story/Epic, real Status), then delete this file.")
    return findings


def check_spec_citations(root):
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in (".md", ".py", ".json"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in SPEC_ID_PATTERN.finditer(line):
                findings.append(f"{rel_of(root, path)}:{lineno} -- '{match.group(0)}' citation. Cite the real "
                                f"GitHub issue number instead.")
    return findings


def main(argv=None):
    global SKILLS_ROOT
    SKILLS_ROOT = _fleet.scan_root(sys.argv[1:] if argv is None else argv, SKILLS_ROOT)
    sections = (
        ("Banned-path check", "banned plan-doc/backlog file(s)", check_banned_paths(SKILLS_ROOT)),
        ("SPEC-N citation check", "SPEC-N citation(s)", check_spec_citations(SKILLS_ROOT)),
        ("History-language check", "history-language line(s) in skill files", check_history_language(SKILLS_ROOT)),
    )
    print(f"Plan-doc leak sweep: scanned {SKILLS_ROOT.name}/\n")
    for title, noun, findings in sections:
        if findings:
            print(f"-- {len(findings)} {noun} --")
            for f in findings:
                print(f"  - {f}")
        else:
            print(f"{title}: clean.")
        print()
    if any(findings for _, _, findings in sections):
        sys.exit(1)


if __name__ == "__main__":
    main()
