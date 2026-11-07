"""Launcher commands that act on the fleet: conform, backlog-setup, sync-hooks, audit-fleet and update."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib import backlog_setup as _backlog_setup
from lib import conform as _conform
from lib.local_config import OC_ROOT
from lib.local_config import private_repos as _private_repos
from lib.local_config import skills_root as _skills_root
from lib.repo_profiles import iter_fleet as _iter_fleet
from lib.repo_profiles import load_repo_profiles, registry_file, registry_gap


def command_conform(oc_root: Path, target: Path | None, fleet_root: Path | None, offline: bool) -> int:
    """`olivercode conform [DIR]`: one repo, or the registered fleet, against docs/CONTRACT.md."""
    print("OliverCode conformance")
    print("=" * 40)
    if target:
        if not target.is_dir():
            print(f"  [FAIL] {target} is not a directory.")
            return 1
        profiles, _ = load_repo_profiles(oc_root)
        profile = next((p for n, p, path in _iter_fleet(profiles, fleet_root or oc_root.parent) if path.resolve() == target.resolve()), {})
        private = target.resolve() in {p.resolve() for p in _private_repos().values()}
        repos = [(target.name, target, bool(profile.get("private")) or private, profile.get("hookVariant", ""))]
    else:
        repos = []
        profiles, _ = load_repo_profiles(oc_root)
        private = {p.resolve() for p in _private_repos().values()}
        for name, profile, path in _iter_fleet(profiles, fleet_root or oc_root.parent):
            if not (path / ".git").exists():
                print(f"  [INFO] {name} is not cloned on this machine")
                continue
            repos.append((name, path, bool(profile.get("private")) or path.resolve() in private, profile.get("hookVariant", "")))
        gap = registry_gap(oc_root)
        if gap:
            print(f"  [FAIL] {gap}")
            return 1
        if not repos:
            print(f"  [SKIP] no fleet registered in {registry_file(oc_root)}")
    failed = 0
    for name, path, private_repo, variant in repos:
        failed += _conform.render(name, _conform.check_repo(path, oc_root=oc_root, offline=offline, private=private_repo, variant=variant))
    print(f"\nChecked {len(repos)} repo(s): {failed} requirement(s) failed")
    return 1 if failed else 0


def command_backlog_setup(argv: list[str]) -> int:
    """`olivercode backlog-setup [DIR] [--apply]`: see lib/backlog_setup.py and docs/SETUP.md."""
    apply = "--apply" in argv
    rest = [a for a in argv if a != "--apply"]
    if len(rest) > 1 or (rest and rest[0].startswith("-")):
        print("Usage: olivercode backlog-setup [DIR] [--apply]")
        return 1
    target = Path(rest[0] if rest else ".").expanduser()
    if not target.is_dir():
        print(f"Error: {target} is not a directory.")
        return 1
    return _backlog_setup.run_setup(target, apply, _backlog_setup.Api(), OC_ROOT)


def _install_pre_push(repo_path: Path, templates_dir: Path) -> None:
    """Deploy pre-push and commit-msg. A declared pre-commit variant still gets both: what is
    safe to push and the story reference every commit carries do not depend on which commit
    gates a repo runs. A repo's `commit-msg.optout` file is never written or removed here."""
    for name in ("pre-push", "commit-msg"):
        _backlog_setup.deploy_hook(repo_path / ".githooks", templates_dir, name)


def _install_hook_pair(repo_path: Path, templates_dir: Path, private_repo: bool) -> None:
    """Idempotently deploy the hook template(s) + hooksPath config to one repo.

    A public repo gets the public template as its live `pre-commit`. A private repo
    (private_repo=True) gets the private template's content deployed AS `pre-commit`,
    because git only auto-invokes that exact filename. No second copy is written, and a
    leftover `pre-commit-private` from an earlier sync is deleted.

    Also deploys `commit-msg` (story reference on every commit) and `pre-push` (force-push/history-rewrite block, secret scan on the push
    range). It has no public/private variant: what is safe to push does not differ by
    repo visibility the way commit-time PII checks do.

    A repo's own pre-commit.local file is never written here. The private
    hook runs it when it exists (GATE-LOCAL-1).

    docs/GATES.md holds the per-variant gate table.
    """
    hooks_dir = repo_path / ".githooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    live_source = templates_dir / ("pre-commit-private" if private_repo else "pre-commit")
    live_target = hooks_dir / "pre-commit"
    live_target.write_bytes(live_source.read_bytes())
    live_target.chmod(0o755)

    (hooks_dir / "pre-commit-private").unlink(missing_ok=True)

    _install_pre_push(repo_path, templates_dir)

    subprocess.run(["git", "-C", str(repo_path), "config", "core.hooksPath", ".githooks"], check=True)


def command_sync_hooks(oc_root: Path, fleet_root: Path | None = None) -> int:
    """Converge hooks + core.hooksPath across every fleet repo and every private repo.

    fleet_root defaults to OliverCode's parent (the sibling-repos layout). A fork whose
    repos live elsewhere passes --root; without that, every repo would silently SKIP as
    "not present on this machine" and the command would still report success.
    """
    templates_dir = oc_root / "core" / "templates" / "project"
    fleet_root = fleet_root or oc_root.parent
    updated = 0
    skipped = 0

    profiles, _ = load_repo_profiles(oc_root)
    for name, profile, repo_path in _iter_fleet(profiles, fleet_root):
        if not (repo_path / ".git").exists():
            print(f"  [SKIP] {name}: not present on this machine")
            skipped += 1
            continue
        variant = profile.get("hookVariant")
        if variant:
            # Declared variant: overwriting its pre-commit would destroy a considered customization.
            # `health` reports it as a WARN. Remove the profile field
            # to bring the repo back under the template.
            _install_pre_push(repo_path, templates_dir)
            print(f"  [SKIP] {name}: declared hook variant ({variant}) — pre-commit left untouched, pre-push and commit-msg synced")
            skipped += 1
            continue
        # A private repo gets the private variant, which drops the PII gate (it holds
        # personal data by design) and adds the archived-content gate. Declared per
        # profile, so every private repo gets its hook from sync-hooks and none is
        # installed by hand and left to go stale on the next template change.
        is_private = bool(profile.get("private"))
        _install_hook_pair(repo_path, templates_dir, private_repo=is_private)
        variant_note = "private-variant " if is_private else ""
        print(f"  [OK] {name}: {variant_note}hooks synced, hooksPath set")
        updated += 1

    for name, root in _private_repos().items():
        if (root / ".git").exists():
            _install_hook_pair(root, templates_dir, private_repo=True)
            print(f"  [OK] {name}: private-variant hook synced, hooksPath set")
            updated += 1
        else:
            print(f"  [SKIP] {name}: no .git at {root}")
            skipped += 1

    print(f"\n{updated} target(s) synced, {skipped} skipped.")
    return 0


def command_audit_fleet(oc_root: Path) -> int:
    """Run the audit skill's structure check against every known skill root.

    Targets exactly 2 roots -- this machine's skills folder (local_config) and
    OliverCode's own skills/ -- not the fleet-repo iteration sync-hooks uses. Fleet
    iteration walks git repos for hook management; this walks 2 known skill-directory
    trees, a different job with a different unit. repo-profiles.json lists repos, which
    hold no skill trees, so reusing it here would scan the wrong places.

    Non-interactive: writes findings to a log file and prints one line per check,
    never fixes anything: a scheduled job with nobody watching never auto-fixes.
    The audit ships in this checkout, so it runs on any machine; the personal skills
    folder is checked only when this machine names one.
    """
    scripts_dir = oc_root / "skills" / "audit" / "scripts"
    if not scripts_dir.is_dir():
        print(f"Error: {scripts_dir} not found -- this checkout is missing skills/audit.")
        return 1

    targets = {"olivercode-skills": oc_root / "skills"}
    skills = _skills_root()
    if skills is None:
        print("  [INFO] no skills folder set for this machine (skillsRoot) — only OliverCode's skills are checked")
    else:
        targets = {"skills": skills, **targets}
    checks = ["check_skill_structure.py"]

    broken = False
    for target_name, target_path in targets.items():
        if not target_path.is_dir():
            print(f"  [SKIP] {target_name}: {target_path} not found")
            continue
        print(f"-- {target_name} ({target_path}) --")
        for check in checks:
            result = subprocess.run(
                ["python3", str(scripts_dir / check), str(target_path)],
                capture_output=True, text=True,
            )
            out_lines = result.stdout.strip().splitlines()
            summary = out_lines[-1] if out_lines else "(no output)"
            # A check exits 1 when it has findings. Any other nonzero exit, or a traceback, means it did not run.
            crashed = result.returncode > 1 or "Traceback" in result.stderr
            broken = broken or crashed
            status = "ERROR" if crashed else "FAIL" if result.returncode != 0 else "ok"
            print(f"  [{status}] {check}: {summary}")

    print("\nFindings are heuristic. Read the flagged locations before treating any as a real "
          "defect -- this command never fixes anything on its own.")
    # Findings exit 0; only a check that could not run exits 1.
    return 1 if broken else 0


def command_update() -> int:
    """Pull this checkout's tracking branch, re-run install, then converge fleet hooks.

    Install runs on every update because a pull can add a skill or a Claude Code hook,
    and only install links those into ~/.claude; without it a second device kept the
    files of a new skill with no link to them. Install and sync-hooks run as new
    processes, so they use the code the pull just brought in, never the copy this
    process loaded before it.

    On a fork `origin` is the FORK, so this does not fetch upstream framework changes.
    Pulling those is a deliberate act with real merge consequences -- a fork carries local
    edits to CLAUDE.md, contracts, and templates, which is the whole point of forking -- so
    it is documented in docs/SETUP.md ("Staying current") and not automated here.
    """
    pull_code = subprocess.run(["git", "-C", str(OC_ROOT), "pull"]).returncode
    if pull_code != 0:
        return pull_code
    launcher = [sys.executable, str(OC_ROOT / "scripts" / "olivercode")]
    print()
    install_code = subprocess.run([*launcher, "install"]).returncode
    print()
    sync_code = subprocess.run([*launcher, "sync-hooks"]).returncode
    return install_code or sync_code
