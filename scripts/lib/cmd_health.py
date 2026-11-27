"""Launcher command `health`: checks on this machine's setup."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from lib import claude_settings as _claude_settings
from lib import queue_shim as _queue_shim
from lib.health_checks import (
    _check_activation_links, _check_managed_hooks_only, _check_stopped_hooks, install_linked, _check_memory, _check_commits_behind, _check_oversized_tracked, _check_remotes_resolve, _check_voice_copies,
    _check_placement_drift, _check_vault_skill_links, _check_python, _check_launcher, _check_path_checkout, _check_gh_version, _check_gh_auth, _check_sleep, _check_worktree_hooks, _check_clean_clone_suite, _check_state_folder,
)
from lib.local_config import OC_ROOT, claude_dir as _claude_dir
from lib.local_config import private_repos as _private_repos
from lib.local_config import skills_root as _skills_root
from lib import repo_state as _repo_state


def _placement_root() -> Path:
    from lib import placement
    return placement.config().root


def spent_worktree_lines() -> list[str]:
    """One line per worktree that is clean with its commits on main, with the command that removes it (#712)."""
    from lib import placement
    return [f"spent worktree {w.path} is clean and its commits are on main. Remove it with `git -C {w.common} worktree remove {w.path}`; `olivercode maintain --fix` removes it nightly"
            for w in placement.worktrees() if w.merged and not w.dirty]


class _HealthTally:
    """Accumulates health-check results.

    WARN does not fail the run: a standalone clone missing local-only context
    (control plane, private repos) must still exit 0 (see docs/SETUP.md).

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


def command_health() -> int:
    """Run health checks on this machine's setup: Claude Code hooks, control plane, skill links, remotes.

    """
    print("OliverCode Health Check")
    print("=" * 40)
    t = _HealthTally()

    t.add(*_check_python())
    t.add(*_check_launcher(OC_ROOT))
    t.add(*_check_path_checkout(_claude_dir() / "CLAUDE.md"))
    t.add(*_check_gh_version())
    t.add(*_check_gh_auth())
    t.add(*_check_sleep())

    # Claude Code hooks. Only a machine where install linked this checkout is expected
    # to carry them; a fresh clone or CI runner has not installed, which is a skip.
    print("\nClaude Code hooks:")
    # A registered hook whose script is gone is reported whether or not install linked this checkout (#1270).
    gone = _claude_settings.dead(_claude_dir() / "settings.json")
    if gone:
        t.fail(f"~/.claude/settings.json runs {len(gone)} hook script(s) that do not exist: "
               f"{', '.join(gone)} — run `olivercode install`")
    if not install_linked(OC_ROOT):
        t.warn("install has not linked this checkout on this machine — hooks not checked")
    else:
        lacking = _claude_settings.missing(_claude_dir() / "settings.json")
        if lacking:
            t.fail(f"~/.claude/settings.json lacks {', '.join(lacking)} for this checkout — run `olivercode install`")
        else:
            t.ok(f"all {len(_claude_settings.MANAGED)} OliverCode hooks are in ~/.claude/settings.json")
        no_allow = _claude_settings.missing_allow(_claude_dir() / "settings.json")
        if no_allow:
            t.fail(f"~/.claude/settings.json permissions.allow lacks {', '.join(no_allow)} — run `olivercode install`")
        else:
            t.ok("permissions.allow holds the tools a session needs")
        gap = _queue_shim.launcher_problem(OC_ROOT)
        if gap:
            t.fail(gap)
        else:
            t.ok("`olivercode` runs from a new shell")
    t.add(*_check_managed_hooks_only())
    otel = bool(os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY")) and any(k.startswith("OTEL_") for k in os.environ)
    print("  [INFO] Claude Code telemetry export is " + ("configured in this environment" if otel else "not configured in this environment"))

    print("\nCheckouts and queues:")
    from lib import maintain
    behind, state = maintain.main_checkout_lag(OC_ROOT)
    if behind:
        t.warn(f"this checkout is {behind} commit(s) behind origin/main and {state}. `olivercode maintain --fix` fast-forwards a clean one")
    from lib import main_checkout
    for repo in [OC_ROOT, *_private_repos().values()]:
        for line in main_checkout.drift(repo):
            t.warn(line)

    # 3. Placement drift (spec: docs/RULES.md "Skill placement").
    # Everything here reads OUTSIDE OC_ROOT (private repos), so it
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
    spent = spent_worktree_lines()
    for line in spent:
        t.warn(line)
    if not spent:
        t.ok("no spent worktrees wait for removal")
    passed, failed, skipped = _check_worktree_hooks()
    t.add(passed, failed, skipped)

    # Permission policy and the context budget (lib/policy.py, lib/context_budget.py).
    print("\nPolicy and context budget:")
    from lib import context_budget, policy
    gaps = [r for r in [OC_ROOT, *_private_repos().values()]
            if (r / ".git").exists() and not (r / policy.POLICY_FILE).is_file()]
    for r in gaps:
        t.warn(f"{r.name} has no permission policy, so no command or path is limited. Run `olivercode policy init {r}` for the default")
    if not gaps:
        t.ok("every governed repo has a permission policy")
    within, text = context_budget.report(OC_ROOT)
    t.ok(text.splitlines()[0]) if within else t.fail(text.splitlines()[0])

    # 5. Topology. The gates cover what goes INTO a commit; these cover whether the
    # pieces are still wired together and recoverable. See health_checks.py for the
    # failure classes.
    print("\nMemory and commits behind:")
    t.add(*_check_memory(OC_ROOT))
    t.add(*_check_commits_behind(OC_ROOT))
    t.add(*_check_clean_clone_suite())
    t.add(*_check_stopped_hooks(OC_ROOT, _private_repos()))
    t.add(*_check_state_folder())

    print("\nActivation links:")
    t.add(*_check_activation_links(_claude_dir()))
    t.add(*_check_vault_skill_links(_skills_root(), OC_ROOT / "skills"))
    t.add(*_check_voice_copies(OC_ROOT, _claude_dir() / "skills"))

    # Scheduled tasks and launchd jobs: every path they name must exist, be tracked and name a live repo (lib/schedules.py).
    print("\nSchedules:")
    from lib import schedules
    found = schedules.check(repo_root=_placement_root())
    for f in found:
        (t.fail if f.level == "FAIL" else t.warn)(f"{f.task}: {f.text}")
    if not found:
        t.ok(f"{schedules.summary()} scheduled tasks and launchd jobs name real tracked paths and ran without repeated interruptions")

    # Repos to check for remote reachability and oversized files: the private repos,
    # and this framework repo.
    topo_repos: list[tuple[str, Path]] = [(n, p) for n, p in _private_repos().items() if (p / ".git").exists() and not _repo_state.skipped(n, p)]
    topo_repos.append((OC_ROOT.name, OC_ROOT))
    t.add(*_check_oversized_tracked(topo_repos))
    t.add(*_check_remotes_resolve(topo_repos))

    print(f"\n{'=' * 40}")
    print(t.summary())
    return 1 if t.failed else 0
