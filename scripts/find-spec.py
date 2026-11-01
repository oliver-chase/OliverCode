#!/usr/bin/env python3
"""Find every backlog entry matching an ID, fleet-wide, in one command.

Nothing namespaces `SPEC-N`/`B-N`-style backlog IDs across repos -- a private skills
repo's backlog and a fleet product repo's own spec backlog both used
`SPEC-21` for two entirely unrelated pieces of work. Renumbering either history is more
disruptive than the collision itself (every commit message and memory note that already
cites the old number would go stale). This script fixes the actual cost instead:
resolving a bare ID took a fleet-wide grep-and-read-both. One command replaces that.

No hardcoded file list. Every `*BACKLOG*.md` under a private repo and every profiled fleet
repo is a candidate -- a new backlog file (a new repo, a renamed ledger) is found the
next run, not after someone remembers to add it here.

Usage:
    scripts/find-spec.py SPEC-21
    scripts/find-spec.py B20 --root /path/to/fleet
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.repo_profiles import load_repo_profiles, iter_fleet  # noqa: E402
from lib.local_config import private_repos  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".obsidian"}
CONTEXT_LINES = 2


def _candidate_files(root: Path):
    """Walk `root`, but never descend into a nested git repo other than `root` itself.

    A private repo can hold fleet repos as real subdirectories, and `iter_fleet` resolves
    those same paths separately. Without this boundary, walking the private repo would
    re-scan every fleet repo's backlog files a second time under a different label --
    caught live: SPEC-21 printed twice, once under the private repo's label and once under
    the same fleet repo's own label, for the exact same 4 lines in the exact same file.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        is_nested_repo = Path(dirpath) != root and (Path(dirpath) / ".git").exists()
        if is_nested_repo:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if "BACKLOG" in name.upper() and name.endswith(".md"):
                yield Path(dirpath) / name


def _search(path: Path, pattern: re.Pattern) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    hits = []
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = max(0, i - CONTEXT_LINES)
            end = min(len(lines), i + CONTEXT_LINES + 1)
            hits.append("\n".join(lines[start:end]))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec_id", help='e.g. "SPEC-21" or "B20"')
    parser.add_argument("--root", default=None,
                         help="directory containing the fleet repos (default: OliverCode's parent)")
    args = parser.parse_args()

    oc_root = Path(__file__).resolve().parent.parent
    fleet_root = Path(args.root).resolve() if args.root else oc_root.parent

    pattern = re.compile(r"\b" + re.escape(args.spec_id) + r"\b")

    # iter_fleet deliberately excludes the framework repo itself (it is not a "fleet"
    # repo to iterate), so OliverCode's own docs/BACKLOG.md (the B-series) needs its
    # own explicit root here or it silently never gets searched -- caught live: a
    # first pass found every SPEC-N but zero B-series IDs.
    roots: list[tuple[str, Path]] = [("olivercode", oc_root)]
    roots += [(name, path) for name, path in private_repos().items() if path.is_dir()]
    profiles, _ = load_repo_profiles(oc_root)
    for name, _profile, repo_path in iter_fleet(profiles, fleet_root):
        if repo_path.is_dir():
            roots.append((name, repo_path))

    total = 0
    for label, root in roots:
        for path in sorted(_candidate_files(root)):
            hits = _search(path, pattern)
            if not hits:
                continue
            rel = path.relative_to(root)
            for hit in hits:
                total += 1
                print(f"[{label}] {rel}")
                print(hit)
                print("---")

    if total == 0:
        print(f"No match for {args.spec_id!r} in any *BACKLOG*.md under a private repo or a fleet repo.")
        if re.match(r"^SPEC-\d+$", args.spec_id):
            print(
                "If the backlog file that held this SPEC-N was retired, its entries may now "
                "live as GitHub issues. Search that repo's GitHub Project for the same ID text."
            )
        return 1
    print(f"{total} match(es) for {args.spec_id!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
