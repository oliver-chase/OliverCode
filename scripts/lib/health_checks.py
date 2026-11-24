"""Health checks: vault skill links, voice and design copies, placement drift, activation links, managed hooks and worktree hook staleness.

`health_topology.py` holds the fleet-location, remote and oversized-file checks, and `health_env.py` holds the
machine-environment checks (memory, commits behind, the clean-clone suite, state folder, fleet repo, python3, gh,
sleep settings and the launcher). This file re-exports both for `cmd_health.py`. Every check returns
(passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import claude_settings as _claude_settings
from lib.local_config import claude_dir as _claude_dir
from lib.local_config import design_file

from lib.skill_links import broken_links, link_states
from lib.skills_catalog import skill_dirs
from lib.health_topology import _check_fleet_locations, _check_oversized_tracked, _check_remotes_resolve  # noqa: E401,F401
from lib.health_env import (  # noqa: E401,F401
    MEMORY_WORDS, _check_memory, _check_commits_behind, SUITE_STALE_DAYS, suite_record_path, _check_clean_clone_suite,
    STATE_KEYS, MIB, state_limits, folder_bytes, _check_state_folder, _check_fleet_repo, _check_python,
    _gh_auth_status, _check_gh_version, _check_gh_auth, _scopes, gh_ready, SLEEP_FIX, sleep_warning, _pmset_text,
    _check_sleep, _check_launcher,
)


def _check_vault_skill_links(skills_root: Path | None, oc_skills: Path | None = None) -> tuple[int, int, int]:
    """Every skill in this machine's skills folder must be symlinked into ~/.claude/skills/.

    A skill under `oc_skills` (OliverCode's own folder) is left to the placement drift check,
    so one bad link prints one FAIL.

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
    if oc_skills is not None:
        declared = [d for d in declared if not d.resolve().is_relative_to(oc_skills.resolve())]
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
    """A self-contained suite's docs/VOICE.md must start with this repo's docs/VOICE.md.

    A suite may add its own sections after the shared text, and any edit to the shared
    text fails.

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
    all_roots = set()
    for link in skills_dir.iterdir():
        if not (link.is_symlink() and link.exists()):
            continue
        skill = link.resolve()
        root = skill.parent.parent
        if skill.parent.name == "skills" and root != oc_root.resolve():
            all_roots.add(root)
            if (root / "docs" / "VOICE.md").is_file():
                suites.add(root)
    if not suites:
        print("  [INFO] no installed suite ships docs/VOICE.md — not checked")
        return 0, 0, 0
    passed = failed = 0
    text = canonical.read_bytes()
    for root in sorted(suites):
        if (root / "docs" / "VOICE.md").read_bytes().startswith(text):
            print(f"  [OK] {root.name}/docs/VOICE.md keeps the shared text")
            passed += 1
        else:
            print(f"  [FAIL] {root.name}/docs/VOICE.md changes the shared text — copy it from {canonical} and keep its own sections after it")
            failed += 1
    # A repo may follow the shipped DESIGN.md or the owner's own designFile (#995), so either one passes and a repo matching neither fails.
    sources = []
    for candidate in (oc_root / "docs" / "DESIGN.md", design_file(oc_root)):
        if candidate.is_file() and candidate.read_bytes() not in [s.read_bytes() for s in sources]:
            sources.append(candidate)
    if sources:
        for root in sorted(r for r in all_roots if (r / "docs" / "DESIGN.md").is_file()):
            text = (root / "docs" / "DESIGN.md").read_bytes()
            if any(text.startswith(source.read_bytes()) for source in sources):
                print(f"  [OK] {root.name}/docs/DESIGN.md keeps the shared text")
                passed += 1
            else:
                print(f"  [FAIL] {root.name}/docs/DESIGN.md changes the shared text — copy it from {design_file(oc_root)} and keep its own sections after it")
                failed += 1
    return passed, failed, 0


def _check_placement_drift(oc_root: Path) -> tuple[int, int, int]:
    print("\nPlacement drift (docs/RULES.md):")
    passed = 0
    failed = 0
    skipped = 0

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
        wrong_target = [n for n, st in states.items() if st == "elsewhere"]
        if oc_skill_names and not installed:
            # Zero symlinks resolve into THIS checkout: it isn't the machine's installed
            # OliverCode (fresh clone, fork, or scratch copy). That's a valid state, not
            # drift, because a stranger's fresh clone must report HEALTHY.
            print(f"  [WARN] this checkout is not the machine's installed OliverCode "
                  f"(no ~/.claude/skills/ symlinks point here) — to install, see docs/SETUP.md")
            skipped += 1
        elif missing:
            print(f"  [FAIL] not symlinked at ~/.claude/skills/: {', '.join(missing)}")
            failed += 1
        elif wrong_target:
            print(f"  [FAIL] symlinked but pointing elsewhere: {', '.join(wrong_target)}")
            failed += 1
        elif "broken" not in states.values():
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
    """Every activation link in ~/.claude must resolve: the checkout link ~/.claude/olivercode, CLAUDE.md, VOICE.md and each skill link.

    A link that points at a moved or deleted checkout loads nothing and says nothing, so the
    session runs without the rules. Install re-points them, so each failure prints that command.
    A missing checkout link fails too, since the documented path then does not resolve (#1082).
    A machine where install never ran has no links, which is a skip.
    """
    passed = failed = 0
    checkout = claude_dir / "olivercode"
    links = [checkout, claude_dir / "CLAUDE.md", claude_dir / "VOICE.md", claude_dir / "DESIGN.md"]
    skills = claude_dir / "skills"
    if skills.is_dir():
        links += sorted(p for p in skills.iterdir() if p.is_symlink())
    if not any(p.is_symlink() for p in links[:3]):
        print("  [WARN] no activation links in ~/.claude, so install has not run here")
        return 0, 0, 1
    if not os.path.lexists(checkout):
        failed += 1
        print(f"  [FAIL] {checkout} is missing, so the documented path ~/.claude/olivercode does not resolve. "
              f"Run `olivercode install` from the OliverCode checkout to create it")
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


MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")


def _check_managed_hooks_only(managed_path: Path = MANAGED_SETTINGS) -> tuple[int, int, int]:
    """Warn when managed settings set `allowManagedHooksOnly` and carry no OliverCode hooks.

    Claude Code then ignores every hook in ~/.claude/settings.json, so the gates stop with no error.
    A user cannot lift the lock, so this is a WARN that names the fix. No managed file, an unreadable
    one or a lock that is off says nothing.
    """
    try:
        managed = json.loads(managed_path.read_text())
    except (OSError, ValueError):
        return 0, 0, 0
    if not isinstance(managed, dict) or managed.get("allowManagedHooksOnly") is not True:
        return 0, 0, 0
    lacking = _claude_settings.missing(managed_path)
    print("\nManaged hooks lock:")
    if not lacking:
        print("  [OK] managed settings lock hooks and carry all OliverCode hooks")
        return 1, 0, 0
    print(f"  [WARN] {managed_path} sets allowManagedHooksOnly, so Claude Code ignores the OliverCode hooks in "
          f"~/.claude/settings.json ({', '.join(lacking)} missing there). Add those hooks to the managed settings, "
          "since a user cannot lift the lock")
    return 0, 0, 1


# The sources a worktree's commit hooks are built from. A worktree builds them from its own branch, so they are older than
# origin/main once main changes any of these after the worktree branched (#902).
GATE_SOURCES = (".githooks", "core/hooks", "scripts/build-hooks.py", "core/templates/project/pre-commit*",
                "core/templates/project/pre-push", "core/templates/project/commit-msg")


def _built_hook_stale(path: Path) -> str:
    """The built hook that differs from a fresh build of this worktree's own gate sources, or "" when they match (#902).
    The built hooks are untracked, so a rebase moves the sources and leaves the old build in place, which git history cannot see."""
    builder = path / "scripts" / "build-hooks.py"
    if not builder.is_file() or not (path / "core" / "hooks").is_dir():
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        (fresh / "scripts").mkdir()
        shutil.copy(builder, fresh / "scripts" / "build-hooks.py")
        shutil.copytree(path / "core" / "hooks", fresh / "core" / "hooks")
        (fresh / "core" / "templates" / "project").mkdir(parents=True)
        if subprocess.run([sys.executable, str(fresh / "scripts" / "build-hooks.py")], capture_output=True).returncode:
            return ""
        for built in sorted((fresh / "core" / "templates" / "project").iterdir()):
            here = path / "core" / "templates" / "project" / built.name
            if not here.is_file() or here.read_bytes() != built.read_bytes():
                return f"core/templates/project/{built.name}"
    return ""


def stale_hook(path: Path, base: str = "origin/main") -> str:
    """Why a worktree's commit hooks predate `base`, or "" when they are current or the worktree has no gates (#902)."""
    from lib import repo_gates
    if not repo_gates.has_gates(path):
        return ""
    if built := _built_hook_stale(path):
        return f"{built} was built before this worktree's gate sources changed"
    fork = subprocess.run(["git", "-C", str(path), "merge-base", "HEAD", base], capture_output=True, text=True)
    if fork.returncode or not fork.stdout.strip():
        return ""
    changed = subprocess.run(["git", "-C", str(path), "diff", "--name-only", fork.stdout.strip(), base, "--", *GATE_SOURCES],
                             capture_output=True, text=True)
    if changed.returncode or not changed.stdout.strip():
        return ""
    return f"{changed.stdout.split()[0]} changed on {base} after this worktree branched"


def _check_worktree_hooks() -> tuple[int, int, int]:
    """Fail each linked worktree whose commit hooks predate origin/main, and name it with its fix (#902). A worktree with no gates says nothing."""
    from lib import placement
    stale = [(wt.path, why) for wt in placement.worktrees() if (why := stale_hook(wt.path))]
    print("\nWorktree hooks:")
    if not stale:
        print("  [OK] every worktree's commit hooks are current with origin/main")
        return 1, 0, 0
    for path, why in stale:
        print(f"  [FAIL] {path} runs commit hooks older than origin/main ({why}). Rebase it with "
              f"`git -C \"{path}\" rebase origin/main`, then run `olivercode worktree fix \"{path}\"`. "
              "Once it is merged, `olivercode clean --apply` removes it")
    return 0, len(stale), 0
PARKED_QUERY = 'is:issue is:open "Parked:" in:comments'


def _parked_numbers(slug: str, run) -> list[int] | None:
    """Open story numbers with a comment starting `Parked:`, the drain's turn-limit park (#1123), from one search call so no per-issue
    comment read is spent. None when the search fails."""
    raw = run(["api", "-X", "GET", "search/issues", "-f", f"q=repo:{slug} {PARKED_QUERY}", "--jq", ".items[].number"])
    return [int(x) for x in raw.split()] if raw is not None else None


def _check_parked_stories(slugs: list[str], run=None) -> tuple[int, int, int]:
    """A story the drain parked on the turn limit twice (#1123) must have a thin story naming it as parent (a body with `Split from #N`),
    so it never sits forgotten in Backlog instead of being split (#1132). A board with no board to check is a skip; a failed search or
    story read on one board only warns, since a parked story on another board is still worth reporting.
    """
    from lib import cmd_groom
    run = run or cmd_groom.gh
    print("\nParked stories:")
    if not slugs:
        print("  [OK] no board to check")
        return 1, 0, 0
    passed = failed = skipped = 0
    for slug in slugs:
        parked = _parked_numbers(slug, run)
        if parked is None:
            print(f"  [WARN] {slug}: could not search for parked stories")
            skipped += 1
            continue
        if not parked:
            passed += 1
            continue
        try:
            stories = cmd_groom.open_stories(slug, run)
        except RuntimeError as exc:
            print(f"  [WARN] {slug}: could not read open stories ({exc})")
            skipped += 1
            continue
        split = {int(n) for s in stories.values() for n in re.findall(r"Split from #(\d+)", s.get("body") or "")}
        unsplit = [n for n in parked if n not in split]
        if not unsplit:
            passed += 1
            continue
        for n in sorted(unsplit):
            title = (stories.get(n) or {}).get("title") or ""
            print(f"  [FAIL] {slug}#{n} ({title}): parked on the turn limit and names no split. File a thin story under its epic "
                  f"naming `Split from #{n}`, sized XS, S or M, then return #{n} to Ready")
        failed += len(unsplit)
    if passed and not failed and not skipped:
        print(f"  [OK] every parked story on {len(slugs)} board(s) has a thin story naming it as parent")
    return passed, failed, skipped

