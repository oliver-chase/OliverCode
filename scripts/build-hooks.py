#!/usr/bin/env python3
"""Build the two pre-commit templates from one ordered gate list, and the pre-push and commit-msg templates.

OliverCode's own .githooks are links to these templates. The public and private templates run the same
gates, so each gate's body lives once in core/hooks/gates/ and this script assembles every variant. The
built hooks are gitignored (HOOK-OUTPUTS-1), so install, bootstrap, sync-hooks and validate.sh
run this script before they read them. A hook is rewritten only when its build differs, through a
temporary file and a rename, so parallel runs never leave a half-written hook.

Usage:
    scripts/build-hooks.py           write the hooks
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OC_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = OC_ROOT / "core" / "hooks" / "gates"
HEADER = OC_ROOT / "core" / "hooks" / "header.sh"
FAILURE_LOG = OC_ROOT / "core" / "hooks" / "failure-log.sh"
# The secret patterns live once and fill both the commit gate and the push hook.
SECRET_PATTERNS = OC_ROOT / "core" / "hooks" / "secret-patterns.sh"
PRE_PUSH = OC_ROOT / "core" / "hooks" / "pre-push.sh"
PRE_PUSH_TARGETS = ("core/templates/project/pre-push",)
# The commit-msg hook is a hook of its own, because git shows a commit message only to
# commit-msg and never to pre-commit. Every variant gets the same one.
COMMIT_MSG_HEADER = """#!/usr/bin/env bash
# Commit-msg hook. Block = no commit.
# Generated from a shared hook source, and `olivercode sync-hooks` replaces a hand edit made here.
# Change it at that source.
# Requires a story reference (#<number>) in every commit message.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
"""
COMMIT_MSG_TARGETS = ("core/templates/project/commit-msg",)
COMMIT_MSG_HEADER += FAILURE_LOG.read_text(encoding="utf-8") + 'GATE_NAME="Commit message"\n'

TITLES = {
    "secrets": "Secrets",
    "pii": "PII",
    "owner-identifiers": "Owner identifiers",
    "version-files": "Version files",
    "repo-local": "Repo-local gates",
}
# Runs after the numbered gates and prints no "Gate N/M" banner, so it is not counted.
UNNUMBERED = {"version-files", "repo-local"}

# The one gate list. Private repos hold personal data by design, so they skip PII and
# the public-repo checks.
VARIANTS = {
    "core/templates/project/pre-commit": {
        "variant": "public repos",
        "gates": ["secrets", "pii", "owner-identifiers", "version-files", "repo-local"],
    },
    "core/templates/project/pre-commit-private": {
        "variant": "private repos",
        "gates": ["secrets", "owner-identifiers", "version-files", "repo-local"],
    },
}


def banner(title: str) -> str:
    head = f"# ─── {title} "
    return head + "─" * max(3, 80 - len(head)) + "\n"


def build(spec: dict) -> str:
    total = sum(1 for g in spec["gates"] if g not in UNNUMBERED)
    parts = [HEADER.read_text(encoding="utf-8").replace("{{VARIANT}}", spec["variant"]),
             FAILURE_LOG.read_text(encoding="utf-8")]
    number = 0
    for gate in spec["gates"]:
        body = (GATES_DIR / f"{gate}.sh").read_text(encoding="utf-8")
        if gate in UNNUMBERED:
            parts.append(banner(TITLES[gate]))
            parts.append(f'GATE_NAME="{TITLES[gate]}"\n')
        else:
            number += 1
            parts.append(banner(f"Gate {number}: {TITLES[gate]}"))
            parts.append(f'GATE_NAME="{TITLES[gate]}"\n')
            body = body.replace("{{N}}", str(number)).replace("{{TOTAL}}", str(total))
        body = body.replace("{{SECRET_PATTERNS}}", SECRET_PATTERNS.read_text(encoding="utf-8"))
        parts.append(body + "\n")
    parts.append(banner("All gates passed"))
    parts.append('echo "[pre-commit] All gates passed."\nexit 0\n')
    return "".join(parts)


def main() -> int:
    pre_push = PRE_PUSH.read_text(encoding="utf-8").replace(
        "{{SECRET_PATTERNS}}", SECRET_PATTERNS.read_text(encoding="utf-8"))
    builds = {rel: build(spec) for rel, spec in VARIANTS.items()}
    builds.update({rel: pre_push for rel in PRE_PUSH_TARGETS})
    commit_msg = COMMIT_MSG_HEADER + (GATES_DIR / "commit-msg.sh").read_text(encoding="utf-8")
    builds.update({rel: commit_msg for rel in COMMIT_MSG_TARGETS})
    for rel, text in builds.items():
        path = OC_ROOT / rel
        if path.is_file() and path.read_text(encoding="utf-8") == text and os.access(path, os.X_OK):
            continue
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.chmod(0o755)
        temp.replace(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
