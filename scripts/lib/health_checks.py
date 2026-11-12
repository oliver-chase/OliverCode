"""Health checks: vault skill links, voice copies, fleet locations, remotes and oversized files.

`cmd_health.py` imports these names. Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from lib.local_config import claude_dir as _claude_dir

from lib.repo_profiles import configured_location, iter_fleet, registry_file
from lib.skill_links import broken_links, link_states
from lib.skills_catalog import skill_dirs

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
    why. Walks nested skill folders, so a skill under any family subfolder is
    still found. The folder comes from local_config; a machine
    with none set has nothing to check here.
    """
    print("\nSkill links:")
    if skills_root is None:
        print("  [INFO] no skills folder set for this machine (skillsRoot) — not checked")
        return 0, 0, 0
    target_dir = _claude_dir() / "skills"

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
            print(f"  [FAIL] {name}: linked to {link.resolve()}; expected {skill_dir}")
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
      - a network error means unverifiable, so it only warns
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


def _check_placement_drift(oc_root: Path) -> tuple[int, int, int]:
    print("\nPlacement drift (docs/RULES.md):")
    passed = 0
    failed = 0
    skipped = 0
    templates_dir = oc_root / "core" / "templates" / "project"

    # (a)/(b) Every OliverCode skill must have a live, correctly-targeted symlink at
    # ~/.claude/skills/<name> -- that's the mechanism making it invocable from any repo.
    # ~/.claude/skills/ is a real directory (not one whole-directory symlink) holding a
    # mix of individual symlinks (orchestration + personal) and real, untracked product/
    # GTM and vendor content -- only the symlinked half is checkable from here.
    claude_skills_dir = _claude_dir() / "skills"
    if not claude_skills_dir.is_dir():
        print("  [WARN] ~/.claude/skills/ not present — skipping")
        skipped += 1
    else:
        skills_dir = oc_root / "skills"
        oc_skill_names = [p.name for p in skill_dirs(skills_dir)] if skills_dir.is_dir() else []
        states = link_states({n: skills_dir / n for n in oc_skill_names}, claude_skills_dir)
        installed = [n for n, st in states.items() if st == "ok"]
        missing = [n for n, st in states.items() if st in ("absent", "real")]
        wrong_target = [n for n, st in states.items() if st in ("broken", "elsewhere")]
        if oc_skill_names and not installed:
            # Zero symlinks resolve into THIS checkout: it isn't the machine's installed
            # OliverCode (fresh clone, fork, or scratch copy). That's a valid state, not
            # drift, because a stranger's fresh clone must report HEALTHY.
            print(f"  [WARN] this checkout is not the machine's installed OliverCode "
                  f"(no ~/.claude/skills/ symlinks point here) — to install, see docs/RULES.md")
            skipped += 1
        elif missing:
            print(f"  [FAIL] not symlinked at ~/.claude/skills/: {', '.join(missing)}")
            failed += 1
        elif wrong_target:
            print(f"  [FAIL] symlinked but pointing elsewhere: {', '.join(wrong_target)}")
            failed += 1
        else:
            print(f"  [OK] all {len(oc_skill_names)} OliverCode skills correctly symlinked at ~/.claude/skills/")
            passed += 1

        broken = broken_links(claude_skills_dir)
        if broken:
            print(f"  [FAIL] broken symlinks in ~/.claude/skills/: {', '.join(broken)}")
            failed += 1
        else:
            passed += 1

    return passed, failed, skipped


def _check_activation_links(claude_dir: Path) -> tuple[int, int, int]:
    """Every activation link in ~/.claude must resolve: CLAUDE.md, VOICE.md and each skill link.

    A link that points at a moved or deleted checkout loads nothing and says nothing, so the
    session runs without the rules. Install re-points them, so each failure prints that command.
    A machine where install never ran has no links, which is a skip.
    """
    passed = failed = 0
    links = [claude_dir / "CLAUDE.md", claude_dir / "VOICE.md"]
    skills = claude_dir / "skills"
    if skills.is_dir():
        links += sorted(p for p in skills.iterdir() if p.is_symlink())
    if not any(p.is_symlink() for p in links[:2]):
        print("  [WARN] no activation links in ~/.claude, so install has not run here")
        return 0, 0, 1
    for link in links:
        if not link.is_symlink():
            continue
        if link.exists():
            passed += 1
        else:
            failed += 1
            print(f"  [FAIL] {link} points at {os.readlink(link)}, which does not exist. "
                  f"Run `olivercode install` from the OliverCode checkout to re-point it")
    if not failed:
        print(f"  [OK] all {passed} activation links resolve")
    return passed, failed, 0


def _check_memory(oc_root: Path) -> tuple[int, int, int]:
    """The memory files stay within memoryWords in docs/BUDGET.json, and an entry that names a gone path is stale.

    Stale entries are listed and never deleted: the owner decides what to drop.
    """
    import json
    import re

    folder = oc_root / ".claude-optimization" / "memory"
    files = sorted(folder.glob("*.md")) if folder.is_dir() else []
    if not files:
        print("  [INFO] no memory files on this machine, so memory is not checked")
        return 0, 0, 0
    passed = failed = skipped = 0
    words = {f.name: len(f.read_text(encoding="utf-8").split()) for f in files}
    budget_file = oc_root / "docs" / "BUDGET.json"
    budget = json.loads(budget_file.read_text(encoding="utf-8")).get("memoryWords") if budget_file.is_file() else None
    total = sum(words.values())
    if budget and total > budget:
        failed += 1
        largest = ", ".join(f"{n} ({w})" for n, w in sorted(words.items(), key=lambda x: -x[1])[:3])
        print(f"  [FAIL] memory holds {total} words, over the {budget} budget by {total - budget}. Largest: {largest}")
    else:
        passed += 1
        print(f"  [OK] memory holds {total} words" + (f" of {budget}" if budget else ""))
    stale = []
    for f in files:
        for ref in sorted(set(re.findall(r"`([~\w./-]+/[\w./-]+|[\w-]+\.(?:md|py|sh|json))`", f.read_text(encoding="utf-8")))):
            if not any((base / ref).expanduser().exists() for base in (oc_root, Path.home())):
                stale.append(f"{f.name}: {ref}")
    if stale:
        skipped += 1
        print("  [WARN] stale memory entries name a path that is gone from here (nothing was deleted):")
        for line in stale[:10]:
            print(f"         {line}")
    else:
        passed += 1
        print("  [OK] no memory entry names a missing path")
    return passed, failed, skipped


def _check_version(oc_root: Path) -> tuple[int, int, int]:
    """Compare VERSION with the `upstream` remote's, and print the changelog entries a fork is missing.

    Reads only refs already fetched, so health stays offline. A checkout with no upstream remote has nothing to compare.
    """
    version_file = oc_root / "VERSION"
    if not version_file.is_file():
        return 0, 0, 0
    local = version_file.read_text().strip()

    def show(path: str) -> str | None:
        out = subprocess.run(["git", "-C", str(oc_root), "show", f"upstream/main:{path}"], capture_output=True, text=True)
        return out.stdout if out.returncode == 0 else None

    upstream = show("VERSION")
    if upstream is None:
        print(f"  [INFO] version {local}; no upstream remote fetched, so no version gap was checked")
        return 0, 0, 0
    upstream = upstream.strip()
    if upstream == local:
        print(f"  [OK] version {local} matches upstream")
        return 1, 0, 0
    have = set((oc_root / "CHANGELOG.md").read_text().splitlines()) if (oc_root / "CHANGELOG.md").is_file() else set()
    missing = [l for l in (show("CHANGELOG.md") or "").splitlines() if l.strip() and l not in have]
    print(f"  [WARN] version {local} differs from upstream {upstream}. Changelog entries you are missing:")
    for line in missing[:15]:
        print(f"         {line}")
    return 0, 0, 1
