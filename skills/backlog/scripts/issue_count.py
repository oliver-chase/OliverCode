#!/usr/bin/env python3
"""Count a repo's issues through the issues list API, never GitHub search (#535).

Usage: issue_count.py OWNER/NAME [open|closed|all]
A search count lags behind the issues a repo holds, so every report that states an open or closed
count calls count_issues. The list API also returns pull requests; they are left out. Exits 0 and prints
the count, or exits 1 when the read fails.
"""
import json
import subprocess
import sys


def gh_list(args):
    return subprocess.run(["gh", "api"] + args, capture_output=True, text=True, timeout=60)


def count_issues(repo, state="open", runner=gh_list):
    """Issues (not pull requests) in `repo` with `state`, or None when the read fails."""
    done = runner(["-X", "GET", f"repos/{repo}/issues", "-f", f"state={state}", "-f", "per_page=100", "--paginate", "--slurp"])
    if done.returncode != 0:
        return None
    try:
        pages = json.loads(done.stdout or "[]")
    except ValueError:
        return None
    rows = [row for page in pages for row in (page if isinstance(page, list) else [page])]
    return sum(1 for row in rows if isinstance(row, dict) and "pull_request" not in row)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] not in ("open", "closed", "all")):
        print("Usage: issue_count.py OWNER/NAME [open|closed|all]", file=sys.stderr)
        return 2
    n = count_issues(argv[0], argv[1] if len(argv) == 2 else "open")
    if n is None:
        print(f"issue_count: the issues of {argv[0]} were not read", file=sys.stderr)
        return 1
    print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
