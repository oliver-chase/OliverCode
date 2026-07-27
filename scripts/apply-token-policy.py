#!/usr/bin/env python3
"""
apply-token-policy.py — Apply token_policy.ignore_globs filtering to a path list.

Usage:
    python3 scripts/apply-token-policy.py <repo-name> <paths...>
    python3 scripts/apply-token-policy.py <repo-name> --file <path-list-file>

Reads paths from stdin (one per line) or a file, filters them against
the repo's token_policy.ignore_globs, and prints the filtered list.
Exits 0. If no path survives filtering, prints nothing (still exits 0).
"""
import fnmatch
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE
# The example file (not the real, gitignored local/repo-profiles.json) is the
# marker — it's the one file guaranteed to exist in every checkout.
while not (REPO_ROOT / "shared" / "repo-profiles.example.json").exists():
    REPO_ROOT = REPO_ROOT.parent
    if REPO_ROOT == Path("/"):
        print("ERROR: Could not find OliverCode root", file=sys.stderr)
        sys.exit(1)

sys.path.insert(0, str(HERE))
from lib.token_policy import token_policy_from_profile
from lib.repo_profiles import load_repo_profiles


def load_profiles() -> dict:
    profiles, _source = load_repo_profiles(REPO_ROOT)
    return profiles


def get_token_policy_simple(profiles: dict, repo_name: str) -> dict:
    """Lenient getter — a missing repo profile returns empty-policy defaults rather
    than exiting (unlike gatekeeper's strict get_repo_profile).

    Lenient, but not silent: with no profile there are no ignore_globs, so every path
    passes through and the caller believes a policy was applied when none was. A typo'd
    repo name is the likely cause, so say so on stderr and leave stdout clean for the
    filtered list.
    """
    if repo_name not in profiles:
        known = ", ".join(sorted(profiles)) or "none"
        print(
            f"WARN: no profile for repo '{repo_name}' — nothing will be filtered. "
            f"Known profiles: {known}",
            file=sys.stderr,
        )
    return token_policy_from_profile(profiles.get(repo_name, {}))


def filter_paths(paths: list, ignore_globs: list) -> list:
    """Return only paths that do NOT match any ignore_glob."""
    return [p for p in paths if not any(fnmatch.fnmatch(p, glob) for glob in ignore_globs)]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply-token-policy.py <repo-name> [paths...]", file=sys.stderr)
        sys.exit(1)

    repo_name = sys.argv[1]
    profiles = load_profiles()
    policy = get_token_policy_simple(profiles, repo_name)
    ignore_globs = policy.get("ignore_globs", [])

    # Collect paths: from --file, trailing args, or stdin
    paths = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--file" and i + 1 < len(sys.argv):
            with open(sys.argv[i + 1]) as f:
                paths.extend(line.strip() for line in f if line.strip())
            i += 2
        else:
            paths.append(sys.argv[i])
            i += 1

    if not paths and not sys.stdin.isatty():
        paths = [line.strip() for line in sys.stdin if line.strip()]

    filtered = filter_paths(paths, ignore_globs)
    for p in filtered:
        print(p)


if __name__ == "__main__":
    main()
