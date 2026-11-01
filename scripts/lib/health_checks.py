"""Health checks: governance-waiver expiry, the GitHub About, and fleet topology.

Extracted from the launcher; it re-exports these names, so callers and tests are
unchanged. Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.repo_profiles import registry_file

def _check_github_about(oc_root: Path) -> tuple[int, int, int]:
    """WARN-degrading check that this repo's GitHub About is filled in.

    docs/DOCUMENTATION-STANDARD.md requires every repo to carry a description and
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
    path = registry_file(oc_root, "repo-map.json")
    if not path.is_file():
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


# ── Topology checks ──────────────────────────────────────────────────────────
# The gates cover CONTENT: no secret, no emoji, no archived copy in a commit.
# Nothing covered TOPOLOGY -- where things live, whether they are still wired
# together, whether they could be recovered. Every failure below ran undetected
# for weeks because no check looked:
#   - two folder repos pointed at a GitHub repo that had been deleted, so
#     neither was backed up anywhere and pushing was impossible
#   - a 423MB blob sat in one of those histories, over GitHub's 100MB per-file
#     hard limit, so that repo could never have pushed even with a live remote
#   - four plugins were symlinked into ~/.claude/plugins by hand, and nothing
#     would have recreated them on another machine (the check this added was
#     retired when plugins moved into the skills folder -- see
#     `_check_vault_skill_links` for the same risk at the skill layer)
# All of them read outside the framework repo, so all of them degrade to WARN
# rather than FAIL when that context is absent: a standalone clone stays HEALTHY.

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
    for skill_dir in declared:
        name = skill_dir.name
        link = target_dir / name
        if not link.exists() and not link.is_symlink():
            print(f"  [FAIL] {name}: not linked into ~/.claude/skills/ — invisible to the Skill tool")
            failed += 1
        elif link.is_symlink() and not link.exists():
            print(f"  [FAIL] {name}: symlink is broken (points at {link.readlink()})")
            failed += 1
        elif link.is_symlink() and link.resolve() != skill_dir.resolve():
            print(f"  [FAIL] {name}: linked to {link.resolve()}, not {skill_dir}")
            failed += 1
        else:
            passed += 1
    if passed and not failed:
        print(f"  [OK] all {passed} skills from skillsRoot linked")
    return passed, failed, 0


SCHEDULER_LABEL = "com.olivercode.local-scheduler"
# Job name, marker file and interval, as scripts/local-scheduler/tick.py writes them.
SCHEDULER_JOBS = (("push-fleet", "last-push-fleet", 3 * 3600), ("audit-fleet", "last-audit-fleet", 7 * 86400))


def _check_scheduler(home: Path) -> tuple[int, int, int]:
    """Report whether the local scheduler is installed and when each job last ran.

    Uninstalled, audit-fleet and push-fleet never run and nothing says so: the fleet audit
    once sat six weeks stale with failures in its last log. A WARN, because the scheduler
    is optional and macOS-only.
    """
    print("\nScheduler:")
    agents = home / "Library" / "LaunchAgents"
    if not agents.is_dir():
        print("  [INFO] no launchd on this machine — not checked")
        return 0, 0, 0
    if not (agents / f"{SCHEDULER_LABEL}.plist").is_file():
        print("  [WARN] not installed, so audit-fleet and push-fleet never run — "
              "bash scripts/local-scheduler/install.sh")
        return 0, 0, 1
    state = home / "Library" / "Application Support" / "olivercode-scheduler"
    passed = skipped = 0
    for name, marker, interval in SCHEDULER_JOBS:
        path = state / marker
        if not path.is_file():
            print(f"  [WARN] {name} has never run")
            skipped += 1
            continue
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        if age > 2 * interval:
            print(f"  [WARN] {name} last ran {age / 86400:.1f} days ago — read its log in {state / 'logs'}")
            skipped += 1
        else:
            print(f"  [OK] {name} ran {age / 3600:.1f} hours ago")
            passed += 1
    return passed, 0, skipped


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


def _check_remotes_resolve(repos: list[tuple[str, Path]]) -> tuple[int, int, int]:
    """Every repo's origin must actually exist on the remote host.

    A deleted or renamed remote is the failure mode with no local symptom at all:
    committing keeps working, `git status` stays clean, and the work is simply not
    backed up anywhere. Two folder repos sat that way for weeks.

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
