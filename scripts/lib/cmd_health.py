"""Launcher command `health`: checks on this machine's setup."""

from __future__ import annotations

import re
from pathlib import Path

from lib import claude_settings as _claude_settings
from lib.health_checks import (
    _check_fleet_locations, _check_oversized_tracked, _check_remotes_resolve, _check_voice_copies,
    _check_placement_drift, _check_vault_skill_links,
)
from lib.local_config import OC_ROOT, claude_dir as _claude_dir
from lib.local_config import private_repos as _private_repos
from lib.local_config import skills_root as _skills_root
from lib.repo_profiles import iter_fleet as _iter_fleet
from lib.repo_profiles import load_repo_profiles


class _HealthTally:
    """Accumulates health-check results.

    WARN does not fail the run: a standalone clone missing local-only context
    (control plane, private repos) must still exit 0 (see docs/RULES.md).

    WARN is counted apart from OK, so the summary claims only the checks that verified
    something, and a skipped check never reads as a pass.
    """

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.failed = 0

    def ok(self, msg: str) -> None:
        print(f"  [OK] {msg}")
        self.passed += 1

    def warn(self, msg: str) -> None:
        print(f"  [WARN] {msg}")
        self.skipped += 1

    def fail(self, msg: str) -> None:
        print(f"  [FAIL] {msg}")
        self.failed += 1

    def add(self, passed: int, failed: int, skipped: int = 0) -> None:
        self.passed += passed
        self.failed += failed
        self.skipped += skipped

    def summary(self) -> str:
        """One line that never overstates what was checked."""
        if self.failed:
            return (f"UNHEALTHY — {self.failed} failed, {self.passed} passed"
                    + (f", {self.skipped} skipped" if self.skipped else ""))
        if self.skipped:
            return (f"HEALTHY — {self.passed} checks passed, {self.skipped} skipped for "
                    f"missing context (see WARN above); nothing failed")
        return f"HEALTHY — {self.passed} checks passed"


def command_health(fleet_root: Path | None = None) -> int:
    """Run health checks on this machine's setup: Claude Code hooks, control plane, skill links, remotes.

    What a repo must match is `command_conform`'s job (docs/CONTRACT.md).
    """
    print("OliverCode Health Check")
    print("=" * 40)
    t = _HealthTally()

    # Claude Code hooks. Only a machine where install linked this checkout is expected
    # to carry them; a fresh clone or CI runner has not installed, which is a skip.
    print("\nClaude Code hooks:")
    claude_md = _claude_dir() / "CLAUDE.md"
    if not (claude_md.is_symlink() and claude_md.resolve() == (OC_ROOT / "CLAUDE.md").resolve()):
        t.warn("install has not linked this checkout on this machine — hooks not checked")
    else:
        lacking = _claude_settings.missing(_claude_dir() / "settings.json")
        if lacking:
            t.fail(f"~/.claude/settings.json lacks {', '.join(lacking)} for this checkout — run `olivercode install`")
        else:
            t.ok(f"all {len(_claude_settings.MANAGED)} OliverCode hooks are in ~/.claude/settings.json")

    # 2. The optional local control plane (runtime/control-plane/, gitignored). A machine
    # without one has nothing to check here, so its absence is not counted as a skip.
    control_plane = OC_ROOT / "runtime" / "control-plane"
    if not control_plane.exists():
        print("  [INFO] no local control plane on this machine — not checked")
    else:
        if (control_plane / "olivercode").exists():
            t.ok("runtime/control-plane/olivercode (launcher)")
        else:
            t.fail("runtime/control-plane/olivercode — control plane present but launcher missing")
        dep_file = control_plane / "OLIVERCODE_DEPENDENCY.md"
        if dep_file.exists():
            oc_dirs = ("shared/", "core/", "docs/", "scripts/", "tooling/", "runtime/", ".githooks/")
            text = dep_file.read_text(encoding="utf-8", errors="ignore")
            declared = [m for m in re.findall(r"`([^`]+)`", text) if m.startswith(oc_dirs)]
            missing = [rel for rel in declared if not (OC_ROOT / rel).exists()]
            if not declared:
                t.warn("no OliverCode-relative dependency paths declared")
            elif not missing:
                t.ok(f"all {len(declared)} declared dependency paths resolve")
            else:
                for rel in missing:
                    t.fail(f"{rel} — not found")

    # 3. Placement drift (spec: docs/RULES.md "Skill placement").
    # Everything here reads OUTSIDE OC_ROOT (private repos, sibling fleet repos), so it
    # must degrade to WARN, never FAIL, when that context isn't present — a standalone
    # clone with no private repos around it is still a valid, healthy checkout.
    passed, failed, skipped = _check_placement_drift(OC_ROOT)
    t.add(passed, failed, skipped)

    # Placement: every repo, worktree and backup under repoRoot (lib/placement.py).
    print("\nPlacement (repoRoot):")
    from lib import placement
    stray = placement.findings()
    for f in stray:
        t.fail(f"{f.kind} out of place: {f.path}. {f.fix}")
    if not stray:
        t.ok("every repo, worktree and backup is under repoRoot")

    # 5. Topology. The gates cover what goes INTO a commit; these cover whether the
    # pieces are still wired together and recoverable. See health_checks.py for the
    # failure classes.
    t.add(*_check_vault_skill_links(_skills_root()))
    t.add(*_check_voice_copies(OC_ROOT, _claude_dir() / "skills"))

    # Repos to check for remote reachability and oversized files: the private repos,
    # this framework repo, and every fleet repo that exists on disk.
    topo_repos: list[tuple[str, Path]] = [(n, p) for n, p in _private_repos().items() if (p / ".git").exists()]
    topo_repos.append((OC_ROOT.name, OC_ROOT))
    _profiles, _ = load_repo_profiles(OC_ROOT)
    for name, _profile, repo_path in _iter_fleet(_profiles, fleet_root or OC_ROOT.parent):
        if repo_path.is_dir():
            topo_repos.append((name, repo_path))

    t.add(*_check_fleet_locations(_profiles, fleet_root or OC_ROOT.parent))
    t.add(*_check_oversized_tracked(topo_repos))
    t.add(*_check_remotes_resolve(topo_repos))

    print(f"\n{'=' * 40}")
    print(t.summary())
    return 1 if t.failed else 0
