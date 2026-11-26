"""Topology checks: a moved repo, a remote that no longer exists and a tracked file over GitHub's size limit.

The gates cover the content of a commit. These checks read outside the framework repo, so each degrades to WARN
when that context is absent and a standalone clone stays HEALTHY. `health_checks.py` re-exports them for `cmd_health.py`.
Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lib.repo_profiles import configured_location, iter_fleet

GITHUB_FILE_LIMIT = 100 * 1024 * 1024


def _check_fleet_locations(profiles: dict, fleet_root: Path) -> tuple[int, int, int]:
    """A registered repo that has a configured location but no repo there has moved, and that is a FAIL.

    Without this a moved repo dropped out of every later check and the report still read healthy.
    A repo with no configured location was never cloned on this machine, which is only a note.
    """
    print("\nFleet repo locations:")
    passed = failed = 0
    for name, profile, path in iter_fleet(profiles, fleet_root):
        if (path / ".git").exists():
            passed += 1
            continue
        where = configured_location(name, profile)
        if where is None:
            print(f"  [INFO] {name} is not cloned on this machine")
            continue
        print(f"  [FAIL] {name}: no repo at {path}. Update {where}")
        failed += 1
    return passed, failed, 0


def _check_remotes_resolve(repos: list[tuple[str, Path]]) -> tuple[int, int, int]:
    """Every repo's origin must actually exist on the remote host.

    A deleted or renamed remote is the failure mode with no local symptom at all:
    committing keeps working, `git status` stays clean, and the work is simply not
    backed up anywhere.

    Only a host that answers and DENIES the repo counts as a FAIL. Two cases that
    look similar are deliberately warnings instead:
      - a network error means unverifiable, so it only warns
      - no origin at all is a local-only repo, which is a legitimate state; a fresh
        `git init` scratch repo has no remote and is not a governance failure
    """
    print("\nRemote reachability:")
    passed = failed = skipped = 0

    def _origin(path: Path) -> str:
        return subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()

    def _probe(args):
        path, url = args
        try:
            return subprocess.run(["git", "-C", str(path), "ls-remote", "--exit-code", "-h", url], capture_output=True, text=True, timeout=25)
        except subprocess.TimeoutExpired:
            return None

    present = [(n, p) for n, p in repos if (p / ".git").exists()]
    urls = {p: _origin(p) for _, p in present}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:  # the probes wait on the network, so they run together
        todo = [(n, p) for n, p in present if urls[p]]
        probed = dict(zip([p for _, p in todo], pool.map(_probe, [(p, urls[p]) for _, p in todo])))
    for name, path in repos:
        if not (path / ".git").exists():
            continue
        url = urls[path]
        if not url:
            print(f"  [WARN] {name}: no origin remote — local only, nothing to verify")
            skipped += 1
            continue
        r = probed.get(path)
        if r is None:
            print(f"  [WARN] {name}: remote check timed out — unverified")
            skipped += 1
            continue
        err = (r.stderr or "").lower()
        if r.returncode == 0:
            passed += 1
        elif "not found" in err or "does not exist" in err or "repository not found" in err:
            print(f"  [FAIL] {name}: origin does not exist ({url}) — this repo is not backed up")
            failed += 1
        elif "could not resolve host" in err or "network" in err or "timed out" in err:
            print(f"  [WARN] {name}: host unreachable — unverified, so only a warning")
            skipped += 1
        else:
            print(f"  [WARN] {name}: origin unverified ({err.strip().splitlines()[0][:70] if err.strip() else 'no detail'})")
            skipped += 1
    if passed and not failed:
        print(f"  [OK] {passed} remote(s) reachable")
    elif not (passed or failed or skipped):
        print("  [WARN] no repo with a remote to check — skipping")
        skipped = 1
    return passed, failed, skipped


def _check_oversized_tracked(repos: list[tuple[str, Path]]) -> tuple[int, int, int]:
    """No tracked file may exceed GitHub's 100MB per-file hard limit.

    Over that, the push is rejected outright -- and if the file is already in
    history, no amount of deleting it from the tree fixes the push. Catching it at
    the tracked-file stage is the only cheap moment.
    """
    print("\nTracked file sizes:")
    passed = failed = skipped = 0
    for name, path in repos:
        if not (path / ".git").exists():
            continue
        r = subprocess.run(["git", "-C", str(path), "ls-files", "-z"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [WARN] {name}: git ls-files failed, so file sizes were not checked")
            skipped += 1
            continue
        over = []
        for rel in filter(None, r.stdout.split("\0")):
            f = path / rel
            try:
                if f.is_file() and f.stat().st_size > GITHUB_FILE_LIMIT:
                    over.append((rel, f.stat().st_size))
            except OSError:
                print(f"  [WARN] {name}: cannot stat {rel}, so it is not in the size check")
                continue
        if over:
            for rel, size in over[:5]:
                print(f"  [FAIL] {name}: {rel} is {size // (1024*1024)}MB — GitHub rejects over 100MB")
            failed += 1
        else:
            passed += 1
    if passed and not failed:
        print(f"  [OK] {passed} repo(s) under the limit")
    elif not (passed or failed or skipped):
        print("  [WARN] no git repo to check — skipping")
        skipped = 1
    return passed, failed, skipped
