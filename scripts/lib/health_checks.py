"""Health checks: governance-waiver expiry, the GitHub About, and fleet topology.

The launcher re-exports these names. Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.repo_profiles import configured_location, iter_fleet, registry_file
from lib.skill_links import link_states

def _check_waiver_expiry(oc_root: Path) -> tuple[int, int, int]:
    """Flag governance exceptions in repo-profiles.json whose `expiresAt` has passed.

    The registry records deliberate exceptions -- repos waived out of the governance
    contract, complexity variances approved with a reason -- and every entry carries an
    `expiresAt`. Nothing read the file. An expiry date that no code checks is not a
    deadline, it is a comment: the waiver simply became permanent on the day it was
    written, which is the opposite of what an expiring waiver is for.

    Reported, never fatal. The point is to make the date mean something at the moment
    someone looks at fleet health, not to block a commit in an unrelated repo.
    """
    path = registry_file(oc_root, "repo-profiles.json")
    if not path.is_file():
        print("  [WARN] no repo-profiles.json — skipping waiver expiry check")
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
    for name, profile in data.get("profiles", {}).items():
        # Both variance kinds carry the same contract: target + reason + expiry.
        for key in ("approvedMaintainabilityVariances", "approvedStrictVariances"):
            for variance in profile.get(key, []):
                entries.append(
                    (f"{name}: {variance.get('target', 'variance')} variance",
                     variance.get("expiresAt", ""), variance.get("reason", ""))
                )

    # An exception with no written reason is unauditable: nobody can later judge
    # whether it still applies, so it can never be safely removed.
    # `or ""`: a JSON null reason is still no reason, and must not crash the health run.
    unreasoned = [label for label, _, reason in entries if not (reason or "").strip()]
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
        except (ValueError, AttributeError):  # AttributeError: a number or list, not a date string
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


# ── Topology checks ──────────────────────────────────────────────────────────
# The gates cover CONTENT: no secret, no emoji, no archived copy in a commit.
# The checks below cover TOPOLOGY -- where things live, whether they are still wired
# together, whether they could be recovered. Each failure class is silent without a check:
#   - two folder repos pointed at a GitHub repo that had been deleted, so
#     neither was backed up anywhere and pushing was impossible
#   - a 423MB blob sat in one of those histories, over GitHub's 100MB per-file
#     hard limit, so that repo could never have pushed even with a live remote
#   - a hand-made symlink that nothing would recreate on another machine (see
#     `_check_vault_skill_links` for the skill layer)
# All of them read outside the framework repo, so all of them degrade to WARN
# when that context is absent, and a standalone clone stays HEALTHY.

GITHUB_FILE_LIMIT = 100 * 1024 * 1024


def _check_vault_skill_links(skills_root: Path | None) -> tuple[int, int, int]:
    """Every skill in this machine's skills folder must be symlinked into ~/.claude/skills/.

    A skill with no matching symlink is invisible to the Skill tool and nothing says
    why. Walks the way `check_skill_structure.py` does, so a skill nested under any
    family subfolder is still found. The folder comes from local_config; a machine
    with none set has nothing to check here.
    """
    print("\nSkill links:")
    if skills_root is None:
        print("  [INFO] no skills folder set for this machine (skillsRoot) — not checked")
        return 0, 0, 0
    target_dir = Path.home() / ".claude" / "skills"

    if not skills_root.is_dir():
        print(f"  [WARN] skills folder {skills_root} not found — skipping")
        return 0, 0, 1
    if not target_dir.is_dir():
        print("  [WARN] ~/.claude/skills/ not present — skipping")
        return 0, 0, 1

    non_skill_dirs = {"docs"}
    declared = []
    for dirpath, dirnames, filenames in os.walk(skills_root):
        dirnames[:] = [d for d in dirnames if d not in non_skill_dirs and not d.startswith(".")]
        if "SKILL.md" in filenames:
            declared.append(Path(dirpath))
            dirnames[:] = []
    declared.sort()

    if not declared:
        print(f"  [WARN] {skills_root} holds no skill with a SKILL.md — skipping")
        return 0, 0, 1

    passed = failed = 0
    states = link_states({d.name: d for d in declared}, target_dir)
    for skill_dir in declared:
        name = skill_dir.name
        link = target_dir / name
        state = states[name]
        if state == "absent":
            print(f"  [FAIL] {name}: not linked into ~/.claude/skills/ — invisible to the Skill tool")
            failed += 1
        elif state == "broken":
            print(f"  [FAIL] {name}: symlink is broken (points at {link.readlink()})")
            failed += 1
        elif state == "elsewhere":
            print(f"  [FAIL] {name}: linked to {link.resolve()}, not {skill_dir}")
            failed += 1
        else:
            passed += 1
    if passed and not failed:
        print(f"  [OK] all {passed} skills from skillsRoot linked")
    return passed, failed, 0


def _check_voice_copies(oc_root: Path, skills_dir: Path) -> tuple[int, int, int]:
    """A self-contained suite's docs/VOICE.md must match this repo's docs/VOICE.md.

    A suite ships its own copy so it runs without OliverCode, and nothing else notices
    when one copy is edited and the others are not. A suite is found from its skills
    linked into ~/.claude/skills (<suite>/skills/<name>), so no machine path is
    configured anywhere.
    """
    print("\nVoice copies:")
    canonical = oc_root / "docs" / "VOICE.md"
    if not canonical.is_file():
        print("  [FAIL] docs/VOICE.md missing — CLAUDE.md imports it through ~/.claude/VOICE.md")
        return 0, 1, 0
    if not skills_dir.is_dir():
        print("  [INFO] ~/.claude/skills/ not present — not checked")
        return 0, 0, 0
    suites = set()
    for link in skills_dir.iterdir():
        if not (link.is_symlink() and link.exists()):
            continue
        skill = link.resolve()
        root = skill.parent.parent
        if skill.parent.name == "skills" and root != oc_root.resolve() and (root / "docs" / "VOICE.md").is_file():
            suites.add(root)
    if not suites:
        print("  [INFO] no installed suite ships docs/VOICE.md — not checked")
        return 0, 0, 0
    passed = failed = 0
    text = canonical.read_bytes()
    for root in sorted(suites):
        if (root / "docs" / "VOICE.md").read_bytes() == text:
            print(f"  [OK] {root.name}/docs/VOICE.md matches")
            passed += 1
        else:
            print(f"  [FAIL] {root.name}/docs/VOICE.md differs — copy it from {canonical}")
            failed += 1
    return passed, failed, 0


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
      - a network error means unverifiable, not broken
      - no origin at all is a local-only repo, which is a legitimate state; a fresh
        `git init` scratch repo has no remote and is not a governance failure
    """
    print("\nRemote reachability:")
    passed = failed = skipped = 0
    for name, path in repos:
        if not (path / ".git").exists():
            continue
        url = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                             capture_output=True, text=True).stdout.strip()
        if not url:
            print(f"  [WARN] {name}: no origin remote — local only, nothing to verify")
            skipped += 1
            continue
        try:
            r = subprocess.run(["git", "-C", str(path), "ls-remote", "--exit-code", "-h", url],
                               capture_output=True, text=True, timeout=25)
        except subprocess.TimeoutExpired:
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
            print(f"  [WARN] {name}: host unreachable — unverified, not a failure")
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
            skipped += 1
            continue
        over = []
        for rel in filter(None, r.stdout.split("\0")):
            f = path / rel
            try:
                if f.is_file() and f.stat().st_size > GITHUB_FILE_LIMIT:
                    over.append((rel, f.stat().st_size))
            except OSError:
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
