#!/usr/bin/env python3
"""Static scan for known MCP-call and token-efficiency anti-patterns.

Reads what a SKILL.md tells the agent to do. Does not trace a real session. Every
finding is "likely" — a human or agent should verify it against a real run before
treating it as a confirmed bug. Stays out of the same-session usage-audit mode's job
(this skill's SKILL.md covers that separately, for one just-run task).

Usage:
    check_mcp_patterns.py                 # scan every skill under the fleet root
    check_mcp_patterns.py <path-or-dir>   # scan one file or folder

Exit 0 if no skill has a mechanical finding. Exit 1 if any skill does. The commit gate runs it.

Tests: python3 -m unittest test_check_mcp_patterns  (run from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT

PER_FIELD_RE = re.compile(
    r"\b(separate search per field|one search per field|search per field|per-field search)\b",
    re.I,
)
PER_FIELD_NEGATION_RE = re.compile(r"\bnot\b[^.]{0,20}\b(one|separate|per-field)\b", re.I)
# An agent word and a parallelism word in one short window, either order. A bare "parallel"
# is a hit only beside "agent", so parallel tool calls and "parallel structure" pass.
PARALLEL_AGENT_RE = re.compile(
    r"\b(parallel|concurrent(ly)?|simultaneous(ly)?|fan-?out|multiple)\b[^.]{0,60}"
    r"\b(sub)?agents?\b|\b(sub)?agents?\b[^.]{0,60}"
    r"\b(parallel|concurrent(ly)?|simultaneous(ly)?|fan-?out)\b",
    re.I,
)
# CONNECTOR-MISSING-1: a skill never tells the person to install, configure or edit
# a connector. A missing connector gets one line, the action plus the fallback.
CONNECTOR_SETUP_RE = re.compile(
    r"(`/mcp`|\bvia /mcp\b|\brun /mcp\b|settings\.json|\bnpx\b[^\n]{0,40}(?:server|mcp)|\bmcpServers\b"
    r"|Settings\s*(?:>|→|->)\s*Connectors)",
    re.I,
)


def gather_text(skill_dir):
    """SKILL.md plus any references/*.md, concatenated for one combined scan."""
    parts = [(skill_dir / "SKILL.md").read_text(encoding="utf-8")]
    refs = skill_dir / "references"
    if refs.is_dir():
        for f in sorted(refs.glob("*.md")):
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def check_text(text):
    """Return a list of (rule, quote) findings for one skill's combined text."""
    findings = []

    m = PER_FIELD_RE.search(text)
    if m and not PER_FIELD_NEGATION_RE.search(text):
        findings.append((
            "per-field-search-loop",
            f"Line contains {m.group(0)!r} — likely a per-field search loop. "
            "Batch by entity first instead.",
        ))

    m = PARALLEL_AGENT_RE.search(text)
    if m:
        findings.append((
            "no-2-subagents-at-once",
            f"Line contains {m.group(0)!r} — reads as an instruction to run 2+ "
            "subagents concurrently. Never run 2 subagents "
            "at once, any task. Sequential, one at a time, or direct execution "
            "instead.",
        ))

    m = CONNECTOR_SETUP_RE.search(text)
    if m:
        findings.append((
            "connector-setup-instruction",
            f"Text contains {m.group(0)!r} — tells the person to configure a connector. "
            "Print one line instead: the admin action and the fallback, then continue.",
        ))

    return findings


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        target = Path(args[0])
        if target.is_file():
            skill_dirs = [target.parent]
        else:
            skill_dirs = _fleet.find_skills(SKILLS_ROOT) if target == SKILLS_ROOT else [target]
    else:
        skill_dirs = _fleet.find_skills(SKILLS_ROOT)

    total_findings = 0
    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        text = gather_text(skill_dir)
        findings = check_text(text)
        if findings:
            total_findings += len(findings)
            print(f"{skill_dir.name}: {len(findings)} likely finding(s)")
            for rule, note in findings:
                print(f"  - [{rule}] {note}")

    if total_findings == 0:
        print("No mechanical MCP-efficiency findings. (Findings here are heuristic — "
              "absence of a flag is not proof of an efficient skill.)")
        sys.exit(0)

    print(f"\n{total_findings} likely finding(s) total. Verify each against a real run "
          "before treating it as a confirmed bug — see this skill's SKILL.md.")
    sys.exit(1)


if __name__ == "__main__":
    main()
