#!/usr/bin/env python3
"""Flag fleet repos whose review/audit coverage is stale.

Deterministic, no LLM: reads the fleet from repo-profiles, locates each repo as a
sibling of OliverCode (override with --root), finds its `Reviewed through: <sha>`
marker — the line core/templates/project/docs/BACKLOG-live-tracker.md standardizes —
and counts commits landed since. Past the threshold it is STALE, which is the signal
to run `deep-review`. Nothing is audited here; staleness is
only made impossible to miss.

A repo with no marker, or one naming a sha its history no longer holds, is a SETUP
gap and is reported separately. Counting those as stale flagged all seven repos at
once while five had simply never been marked, and a signal that is always on is one
nobody reads.

Usage:
  python3 scripts/audit-staleness.py [--root <dir>] [--threshold N] [--quiet]

Exit 0 = every marked repo is inside the threshold, 1 = at least one has drifted past
it, so a cron wrapper can alert on nonzero. Unmarked repos do not set it.
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
    p = olivercode_root / "shared" / "repo-profiles.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text()).get("profiles", {})
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARN: could not parse {p}: {exc}", file=sys.stderr)
        return {}


def _load_governance_profiles(olivercode_root: Path) -> dict[str, str]:
    """name -> governanceProfile, from shared/repo-map.json.

    The only recognized value is "incubating": the repo is young or mid-overhaul,
    so staleness is reported but does not fail the run. Anything else is reported
    as unknown so a typo cannot silently exempt a repo. This is the field's one
    consumer -- before it, a declared profile changed nothing anywhere.
    """
    f = olivercode_root / "shared" / "repo-map.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        r.get("name", ""): r.get("governanceProfile", "")
        for r in data.get("repos", []) if r.get("governanceProfile")
    }


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
        print("No repo profiles found (shared/repo-profiles.json).", file=sys.stderr)
        return 1

    governance = _load_governance_profiles(olivercode_root)
    any_flagged = False
    unmarked: list[str] = []
    broken: list[tuple[str, str]] = []
    for name in sorted(profiles):
        # Same resolution rule as the launcher: an explicit profile `path` wins over
        # the sibling convention, so a scattered fleet is auditable too.
        declared = profiles[name].get("path") if isinstance(profiles[name], dict) else None
        if declared:
            repo = Path(declared).expanduser()
            if not repo.is_absolute():
                repo = fleet_root / repo
        else:
            repo = fleet_root / name
        incubating = governance.get(name) == "incubating"
        if governance.get(name) and not incubating:
            print(f"  WARN {name}: unknown governanceProfile "
                  f"'{governance[name]}' in repo-map -- only 'incubating' is recognized")
        if not (repo / ".git").exists():
            if not args.quiet:
                print(f"  skip  {name}: not found at {repo}")
            continue
        sha = _find_marker(repo)
        if sha is None:
            unmarked.append(name)
            continue
        count = _commits_since(repo, sha)
        if count is None:
            broken.append((name, sha[:9]))
            continue
        if count > args.threshold:
            if incubating:
                print(f"  ok   {name}: {count} commits since {sha[:9]} -- past threshold but "
                      f"declared incubating in repo-map, advisory only")
            else:
                any_flagged = True
                print(f"STALE  {name}: {count} commits since last review ({sha[:9]}) -- run deep-review")
        elif not args.quiet:
            print(f"  ok   {name}: {count} commits since {sha[:9]}")

    # Unmarked and broken-marker repos are a SETUP gap, not a review-cadence one, and
    # they are reported apart from STALE rather than counted with it. Every repo in the
    # fleet failed this check at once while five had simply never been marked, and a
    # signal that is always on is one nobody reads. The exit code now means "a repo
    # that IS tracked has drifted past the threshold", which is a thing to act on.
    if unmarked:
        print(f"\nUNMARKED ({len(unmarked)}): {', '.join(unmarked)}")
        print("  No 'Reviewed through: `<sha>`' line in any ledger. Add one when a "
              "deep-review lands; until then coverage here is unknown, not fresh.")
    if broken:
        print(f"\nMARKER BROKEN ({len(broken)}): " + ", ".join(f"{n} ({s})" for n, s in broken))
        print("  The marker names a sha the repo does not have, usually a rewritten "
              "history. Worse than no marker, because it reads as a real coverage claim.")

    return 1 if any_flagged else 0


if __name__ == "__main__":
    sys.exit(main())
