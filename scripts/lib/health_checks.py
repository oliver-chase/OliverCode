"""Health checks with no fleet-walking: governance-waiver expiry and the GitHub About.

Extracted from the launcher; it re-exports these names, so callers and tests are
unchanged. Both checks return (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

def _local_or_shared(oc_root: Path, filename: str) -> Path | None:
    """Resolve a registry the same way every other loader does: local/ overlay first,
    tracked shared/ placeholder as the fallback, None if neither exists."""
    for candidate in (oc_root / "local" / filename, oc_root / "shared" / filename):
        if candidate.is_file():
            return candidate
    return None

def _check_github_about(oc_root: Path) -> tuple[int, int, int]:
    """WARN-degrading check that this repo's GitHub About is filled in.

    docs/DOCUMENTATION_STANDARD.md requires every repo to carry a description and
    topics. No gate can see GitHub, so this is the one place the requirement is
    checked at all. Degrades to a skip without `gh`, without auth, or without a
    network -- a fork working offline must still report healthy.
    """
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "description,repositoryTopics"],
            capture_output=True, text=True, timeout=15, cwd=str(oc_root),
        )
    except (OSError, subprocess.TimeoutExpired):
        print("  [WARN] gh unavailable — cannot check the About section")
        return 0, 0, 1
    if out.returncode != 0:
        print("  [WARN] gh cannot reach the repo (no auth/remote/network) — skipping About check")
        return 0, 0, 1
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        print("  [WARN] unexpected gh output — skipping About check")
        return 0, 0, 1
    desc = (data.get("description") or "").strip()
    topics = data.get("repositoryTopics") or []
    if not desc:
        print("  [FAIL] GitHub About description is empty — the documentation standard "
              "treats this as missing documentation (gh repo edit --description ...)")
        return 0, 1, 0
    if not topics:
        print("  [WARN] About description set but no topics — add the real domains "
              "(gh repo edit --add-topic ...)")
        return 0, 0, 1
    print(f"  [OK] About: description set, {len(topics)} topic(s)")
    return 1, 0, 0

def _check_waiver_expiry(oc_root: Path) -> tuple[int, int, int]:
    """Flag governance exceptions in repo-map.json whose `expiresAt` has passed.

    repo-map.json records deliberate exceptions -- repos waived out of the governance
    contract, complexity variances approved with a reason -- and every entry carries an
    `expiresAt`. Nothing read the file. An expiry date that no code checks is not a
    deadline, it is a comment: the waiver simply became permanent on the day it was
    written, which is the opposite of what an expiring waiver is for.

    Reported, never fatal. The point is to make the date mean something at the moment
    someone looks at fleet health, not to block a commit in an unrelated repo.
    """
    path = _local_or_shared(oc_root, "repo-map.json")
    if path is None:
        print("  [WARN] no repo-map.json — skipping waiver expiry check")
        return 0, 0, 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  [FAIL] {path.name} is unreadable: {exc}")
        return 0, 1, 0

    now = datetime.now(timezone.utc)
    entries: list[tuple[str, str, str]] = []  # (label, expiresAt, reason)
    for waiver in data.get("unmanagedRepoWaivers", []):
        entries.append((f"unmanaged-repo waiver for {waiver.get('name', '?')}",
                        waiver.get("expiresAt", ""), waiver.get("reason", "")))
    for repo in data.get("repos", []):
        # Both variance kinds carry the same contract: target + reason + expiry.
        for key in ("approvedMaintainabilityVariances", "approvedStrictVariances"):
            for variance in repo.get(key, []):
                entries.append(
                    (f"{repo.get('name', '?')}: {variance.get('target', 'variance')} variance",
                     variance.get("expiresAt", ""), variance.get("reason", ""))
                )

    # An exception with no written reason is unauditable: nobody can later judge
    # whether it still applies, so it can never be safely removed.
    unreasoned = [label for label, _, reason in entries if not reason.strip()]
    for label in unreasoned:
        print(f"  [FAIL] {label}: no reason recorded — an exception without a reason "
              f"can never be reviewed or retired")

    dated = [(label, raw) for label, raw, _ in entries if raw]
    if not dated and not unreasoned:
        print("  [OK] no dated governance waivers to expire")
        return 1, 0, 0

    expired = []
    unparsable = []
    for label, raw in dated:
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            unparsable.append(label)
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < now:
            expired.append((label, when))

    for label in unparsable:
        print(f"  [FAIL] {label}: expiresAt is not an ISO-8601 date — it can never expire")
    for label, when in expired:
        days = (now - when).days
        print(f"  [FAIL] {label}: EXPIRED {days}d ago ({when.date()}) — renew it with a new "
              f"reason and date, or remove the waiver and fix the underlying issue")
    if expired or unparsable or unreasoned:
        return 0, len(expired) + len(unparsable) + len(unreasoned), 0

    # Normalize before comparing: min() over a mix of offset-naive and offset-aware
    # datetimes raises TypeError, so one waiver written without a timezone crashed the
    # whole health run. The expiry loop above already normalizes; this must match it.
    def _aware(raw: str) -> datetime:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    soonest = min(_aware(r) for _, r in dated)
    print(f"  [OK] {len(dated)} waiver(s) current; next expires {soonest.date()}")
    return 1, 0, 0
