#!/usr/bin/env python3
"""Write `.githooks/ste-baseline`: the hard-violation count Gate 4 accepts per file, frozen at
adoption. GATE-BASELINE-1 in OliverCode's docs/DECISIONS.md.

Gate 4 (writing clarity) only ever checked SKILL.md/CLAUDE.md before GATE-SCOPE-1 extended it
to references/*.md. A repo's existing reference files can carry real pre-existing debt that
gate never saw -- committing an unrelated one-line fix to such a file would then have to clear
all of it first, which would fail a thousand times on day one. This script freezes that debt
at adoption instead.

A file not listed here has baseline 0 -- any hard violation blocks, same as today. A file
listed here passes as long as its hard-violation count does not exceed its frozen baseline;
fixing some of its debt still passes, and a brand NEW violation on top of the baseline still
blocks, because the count would then exceed it. Delete a line once that file reaches 0 real
violations -- never add one by hand, and never raise a number that's already written down.

Usage:
    write-ste-baseline.py <repo-root> [--ste-lint /path/to/ste-lint.py]
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOIN_WRAPPER = HERE / "ste-lint-joined.py"


def tracked_files(repo_root: Path):
    """Git-tracked files only -- matches what Gate 4 can ever actually see staged.
    A raw filesystem walk also picked up gitignored worktree copies (.claude/worktrees/),
    padding the baseline with debt nothing will ever commit."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, capture_output=True, text=True)
    return [repo_root / p for p in out.stdout.split("\0") if p]


def scoped_files(repo_root: Path):
    for p in tracked_files(repo_root):
        if p.name in ("SKILL.md", "CLAUDE.md"):
            yield p
        elif p.parent.name == "references" and p.suffix == ".md":
            yield p


def hard_count(ste_lint: Path, path: Path) -> int:
    out = subprocess.run(
        [sys.executable, str(JOIN_WRAPPER), str(ste_lint), "--json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(out.stdout)["hard_count"]
    except (json.JSONDecodeError, KeyError):
        print(f"warn: could not read hard_count for {path}: {out.stdout[:200]}", file=sys.stderr)
        return 0


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    repo_root = Path(argv[0]).resolve()
    ste_lint = Path(argv[2]) if len(argv) > 2 and argv[1] == "--ste-lint" else None
    if ste_lint is None:
        for candidate in (
            Path.home() / ".claude/skills/asd-ste100/scripts/ste-lint.py",
            Path.home() / ".agents/skills/asd-ste100/scripts/ste-lint.py",
        ):
            if candidate.is_file():
                ste_lint = candidate
                break
    if ste_lint is None or not ste_lint.is_file():
        print("error: ste-lint.py not found; pass --ste-lint <path>", file=sys.stderr)
        return 2

    rows = []
    for path in sorted(scoped_files(repo_root)):
        count = hard_count(ste_lint, path)
        if count > 0:
            rel = path.relative_to(repo_root)
            rows.append(f"{rel}:{count}")

    out_path = repo_root / ".githooks" / "ste-baseline"
    out_path.write_text("\n".join(rows) + ("\n" if rows else ""))
    print(f"wrote {out_path} with {len(rows)} file(s) carrying real debt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
