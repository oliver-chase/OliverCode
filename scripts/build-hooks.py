#!/usr/bin/env python3
"""Build the three pre-commit hooks from one ordered gate list.

OliverCode's own hook, the public template and the private template run the same
gates. Kept by hand, they drifted: a fix reached one copy and missed another, and
two blocked-commit messages pointed at paths that did not exist. Each gate's body
now lives once in core/hooks/gates/, and this script assembles every variant.

Usage:
    scripts/build-hooks.py           write the three hooks
    scripts/build-hooks.py --check   exit 1 when a committed hook differs from the build
"""
from __future__ import annotations

import sys
from pathlib import Path

OC_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = OC_ROOT / "core" / "hooks" / "gates"
HEADER = OC_ROOT / "core" / "hooks" / "header.sh"

TITLES = {
    "secrets": "Secrets",
    "emojis": "Icons / Emojis",
    "pii": "PII",
    "deleted-repos": "Deleted Repository References",
    "workflow-auth": "Workflow push auth safety",
    "contract-integrity": "Contract integrity",
    "planning-docs": "Planning doc governance",
    "token-policy": "Token policy",
    "backlog-hygiene": "Backlog hygiene",
    "archived-content": "Archived content",
    "writing-clarity": "Writing clarity (asd-ste100)",
    "repo-local": "Repo-local gates",
}
# Runs after the numbered gates and prints no "Gate N/M" banner, so it is not counted.
UNNUMBERED = {"repo-local"}

# The one gate list. Private repos hold personal data by design, so they skip PII and
# the public-repo checks. Contract integrity and token policy check OliverCode's own
# control plane, which no adopted repo has.
VARIANTS = {
    ".githooks/pre-commit": {
        "variant": "OliverCode itself",
        "backlog_checker": "core/templates/project/scripts/check-backlog-hygiene.mjs",
        "gates": ["secrets", "emojis", "pii", "deleted-repos", "workflow-auth",
                  "contract-integrity", "planning-docs", "token-policy",
                  "backlog-hygiene", "archived-content", "writing-clarity"],
    },
    "core/templates/project/pre-commit": {
        "variant": "public repos",
        "backlog_checker": "scripts/check-backlog-hygiene.mjs",
        "gates": ["secrets", "emojis", "pii", "deleted-repos", "workflow-auth",
                  "planning-docs", "backlog-hygiene", "archived-content",
                  "writing-clarity"],
    },
    "core/templates/project/pre-commit-private": {
        "variant": "private repos",
        "backlog_checker": "scripts/check-backlog-hygiene.mjs",
        "gates": ["secrets", "emojis", "archived-content", "writing-clarity",
                  "repo-local"],
    },
}


def banner(title: str) -> str:
    head = f"# ─── {title} "
    return head + "─" * max(3, 80 - len(head)) + "\n"


def build(spec: dict) -> str:
    total = sum(1 for g in spec["gates"] if g not in UNNUMBERED)
    parts = [HEADER.read_text(encoding="utf-8").replace("{{VARIANT}}", spec["variant"])]
    number = 0
    for gate in spec["gates"]:
        body = (GATES_DIR / f"{gate}.sh").read_text(encoding="utf-8")
        if gate in UNNUMBERED:
            parts.append(banner(TITLES[gate]))
        else:
            number += 1
            parts.append(banner(f"Gate {number}: {TITLES[gate]}"))
            body = body.replace("{{N}}", str(number)).replace("{{TOTAL}}", str(total))
        parts.append(body.replace("{{BACKLOG_CHECKER}}", spec["backlog_checker"]) + "\n")
    parts.append(banner("All gates passed"))
    parts.append('echo "[pre-commit] All gates passed."\nexit 0\n')
    return "".join(parts)


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for rel, spec in VARIANTS.items():
        path = OC_ROOT / rel
        text = build(spec)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(rel)
        else:
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)
    for rel in stale:
        print(f"  [HOOKS] {rel} differs from the build. Edit core/hooks/ and run "
              f"scripts/build-hooks.py; never edit a generated hook by hand.")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
