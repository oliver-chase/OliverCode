#!/usr/bin/env python3
"""audit-staleness.py — flag fleet repos whose review/audit coverage is stale.

Deterministic (no LLM): reads the fleet from repo-profiles
(local/repo-profiles.json, falling back to shared/repo-profiles.example.json),
locates each repo as a sibling directory of OliverCode (override with
--root), finds its coverage marker, and counts commits landed since.

The coverage marker is the line the live-session-tracker template
(core/templates/project/docs/BACKLOG-live-tracker.md) standardizes:

    Reviewed through: `<sha>`

searched in the repo's BACKLOG/ledger docs. A repo past the threshold
(default 30 commits since the marker, or no marker at all) is flagged —
that's the signal to run the `deep-review` or `functionality-audit`
skill on it. This script never runs an audit itself; it only makes
staleness impossible to miss.

Usage:
  python3 scripts/audit-staleness.py [--root <dir>] [--threshold N] [--quiet]

Exit codes: 0 = all fresh, 1 = at least one repo stale/unmarked (so a
cron/keepalive wrapper can alert on nonzero).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MARKER_RE = re.compile(r"Reviewed through:\s*`?([0-9a-f]{7,40})`?", re.IGNORECASE)
# Ledger candidates, most-specific first — repos name their ledger differently.
LEDGER_CANDIDATES = (
    "docs/BACKLOG.md",
    "docs/AUDIT_BACKLOG.md",
    "BACKLOG.md",
    "docs/backlog.md",
)


def _load_profiles(olivercode_root: Path) -> dict:
    for rel in ("local/repo-profiles.json", "shared/repo-profiles.example.json"):
        p = olivercode_root / rel
        if p.is_file():
            try:
                return json.loads(p.read_text()).get("profiles", {})
            except (json.JSONDecodeError, OSError) as exc:
                print(f"WARN: could not parse {p}: {exc}", file=sys.stderr)
    return {}


def _find_marker(repo: Path) -> str | None:
    for rel in LEDGER_CANDIDATES:
        f = repo / rel
        if not f.is_file():
            continue
        match = MARKER_RE.search(f.read_text(errors="replace"))
        if match:
            return match.group(1)
    return None


def _commits_since(repo: Path, sha: str) -> int | None:
    """Commit count sha..HEAD, or None if the sha is unknown to the repo
    (rewritten history, marker typo)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", f"{sha}..HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=None,
                        help="directory containing the fleet repos (default: OliverCode's parent)")
    parser.add_argument("--threshold", type=int, default=30,
                        help="commits since the marker before a repo is flagged stale (default 30)")
    parser.add_argument("--quiet", action="store_true", help="only print flagged repos")
    args = parser.parse_args()

    olivercode_root = Path(__file__).resolve().parent.parent
    fleet_root = Path(args.root).resolve() if args.root else olivercode_root.parent
    profiles = _load_profiles(olivercode_root)
    if not profiles:
        print("No repo profiles found (local/repo-profiles.json or the example).", file=sys.stderr)
        return 1

    any_flagged = False
    for name in sorted(profiles):
        repo = fleet_root / name
        if not (repo / ".git").exists():
            if not args.quiet:
                print(f"  skip  {name}: not found at {repo}")
            continue
        sha = _find_marker(repo)
        if sha is None:
            any_flagged = True
            print(f"STALE  {name}: no 'Reviewed through' marker in any ledger "
                  f"({', '.join(LEDGER_CANDIDATES[:2])}...) -- never deep-reviewed, or tracker missing")
            continue
        count = _commits_since(repo, sha)
        if count is None:
            any_flagged = True
            print(f"STALE  {name}: marker sha {sha[:9]} unknown to the repo (history rewrite? typo?)")
            continue
        if count > args.threshold:
            any_flagged = True
            print(f"STALE  {name}: {count} commits since last review ({sha[:9]}) -- run deep-review")
        elif not args.quiet:
            print(f"  ok   {name}: {count} commits since {sha[:9]}")

    return 1 if any_flagged else 0


if __name__ == "__main__":
    sys.exit(main())
