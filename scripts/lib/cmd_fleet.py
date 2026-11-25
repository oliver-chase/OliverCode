"""Launcher commands that act on the fleet: conform, backlog-setup, sync-hooks and update."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lib import backlog_setup as _backlog_setup
from lib import conform as _conform
from lib import repo_gates, repo_profiles
from lib import update_state
from lib import validate_snippet as _snippet
from lib.cli import require_dir, take_flag
from lib.gitfiles import commit_after, commit_changes
from lib import cmd_owner as _owner
from lib.local_config import OC_ROOT
from lib import repo_state as _repo_state
from lib.local_config import private_repos as _private_repos
from lib.repo_profiles import iter_fleet as _iter_fleet
from lib.repo_profiles import NO_FLEET, load_repo_profiles, registry_file, registry_gap


def command_conform(oc_root: Path, target: Path | None, fleet_root: Path | None, offline: bool, hooks_only: bool = False, fix: bool = False, story: str = "") -> int:
    """`olivercode conform [DIR] [--fix --story REF]`: one repo, or the registered fleet, against docs/CONTRACT.md. `--fix` repairs what it can in one commit per repo."""
    print("OliverCode conformance")
    print("=" * 40)
    if target:
        if not target.is_dir():
            print(f"  [FAIL] {target} is not a directory.")
            return 1
        profiles, _ = load_repo_profiles(oc_root)
        if _repo_state.skipped(target.name, target):
            return 0
        profile = next((p for n, p, path in _iter_fleet(profiles, fleet_root or oc_root.parent, skip_archived=False) if path.resolve() == target.resolve()), {})
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
            fleet_message = NO_FLEET[0].upper() + NO_FLEET[1:]
            if private:
                reading = registry_file(oc_root)
                elsewhere = repo_profiles.registries_with_profiles(fleet_root or oc_root.parent, reading)
                if elsewhere:
                    fleet_message = (f"Profiles are in {', '.join(map(str, elsewhere))}. Copy them into {reading}, "
                                     "or name that file with `fleetRegistry` in olivercode.local.json")
                print(f"  [FAIL] the fleet registry is empty in {reading}, so no repo was checked. {fleet_message}")
                return 1
            print(f"  [SKIP] no fleet registered in {registry_file(oc_root)}. {fleet_message}")
        if repos:
            print("\nRepo names:")
            from lib import cmd_health
            cmd_health.repo_names_check(profiles, fleet_root or oc_root.parent)  # an open name question is a warning, so the result does not change the exit code (#1034)
    results, settings = _conform.check_fleet(repos, oc_root=oc_root, offline=offline, hooks_only=hooks_only)
    failed = 0
    for (name, _, _, _), rows in zip(repos, results):
        failed += _conform.render(name, rows)
    print(f"\nChecked {len(repos)} repo(s): {failed} requirement(s) failed")
    if fix and failed:
        failed = _fix_fleet(oc_root, repos, results, settings, offline, hooks_only, story)
    return 1 if failed else 0


def _local_fix(oc_root: Path, repo: Path, kinds: set[str], private: bool, variant: str) -> tuple[tuple[str, ...] | None, object]:
    """(the paths the repo's local fixes touch, None when unknown; the function that applies them)."""
    manifest = json.loads((oc_root / "shared" / "project-bootstrap-manifest.json").read_text()).get("templatedFiles", [])
    touches: list[str] = []
    if "hooks" in kinds:
        touches += MANAGED_PATHS
    if "managed-files" in kinds:
        touches += [e["target"] for e in manifest if e.get("mode") == "strict"]
    if "permission-policy" in kinds:
        touches.append(".olivercode/policy.json")

    def apply() -> None:
        if "hooks" in kinds:
            templates = repo_gates.hook_templates(oc_root)
            if variant:
                _install_pre_push(repo, templates)
                _set_hooks_path(repo)
            else:
                _install_hook_pair(repo, templates, private_repo=private)
            _queue_block(oc_root, repo.name, repo)
        for kind, args in (("managed-files", ["bootstrap", str(repo)]), ("permission-policy", ["policy", "init", str(repo)])):
            if kind in kinds:
                done = subprocess.run([sys.executable, str(oc_root / "scripts" / "olivercode"), *args], capture_output=True, text=True)
                if done.returncode:
                    lines = (done.stderr or done.stdout).strip().splitlines()
                    raise RuntimeError(f"`olivercode {' '.join(args)}` failed" + (f": {lines[-1]}" if lines else ""))
    return tuple(touches), apply


def _fix_fleet(oc_root: Path, repos: list, results: list, settings: dict | None, offline: bool, hooks_only: bool, story: str) -> int:
    """`conform --fix` (#778): per repo, run each local fix, commit them together, set GitHub settings the owner owns, queue the owner steps, then check again."""
    print("\nFixing")
    print("=" * 40)
    skipped: list[tuple[str, str, str]] = []
    for (name, path, private, variant), rows in zip(repos, results):
        failing = [r for r in rows if r.status == "fail"]
        local = {r.requirement for r in failing if _conform.fix_kind(r) == "local"}
        if _repo_state.archived(path):
            print(f"  [SKIP] {name}: archived on GitHub, nothing to fix")
            continue
        if local:
            touches, apply = _local_fix(oc_root, path, local, private, variant)
            try:
                result = commit_after(path, apply, f"Bring the repo in line with the OliverCode contract ({story})",
                                      "Fixes: " + ", ".join(sorted(local)) + " (olivercode conform --fix).", touches)
            except (RuntimeError, OSError, ValueError) as exc:
                result = f"not committed, a fix failed: {exc}"
            if not result.startswith("committed"):
                next_step = _skip_fix(result, path, story)
                skipped.append((name, result, next_step))
                print(f"  [SKIP] {name}: {result}\n         Fix: {next_step}")
            else:
                print(f"  [FIX] {name}: {result}")
        slug = _conform.repo_slug(path)
        owned = bool(((settings or {}).get(f"{slug[0]}/{slug[1]}".lower()) or {}).get("viewerCanAdminister")) if slug else False
        for row in (r for r in failing if _conform.fix_kind(r) != "local"):
            if _conform.fix_kind(row) == "github" and owned and not offline:
                done = subprocess.run(["gh", "repo", "edit", f"{slug[0]}/{slug[1]}", "--delete-branch-on-merge"], capture_output=True, text=True)
                print(f"  [{'FIX' if done.returncode == 0 else 'FAIL'}] {name}: {row.requirement} set on GitHub")
                if done.returncode == 0:
                    continue
            item = _owner.add("conform", f"{name}: {row.requirement} needs the owner", command=row.fix.strip("`"), error=row.detail or row.requirement)
            print(f"  [OWNER] {name}: {row.requirement} is owner queue item {item['id']}: {row.fix}")
    print("\nChecking again")
    print("=" * 40)
    again, _ = _conform.check_fleet(repos, oc_root=oc_root, offline=offline, hooks_only=hooks_only)
    left = sum(_conform.render(name, rows) for (name, _, _, _), rows in zip(repos, again))
    print(f"\nAfter --fix: {left} requirement(s) still fail")
    for name, result, next_step in skipped:
        print(f"  Skipped {name}: {result.removeprefix('not committed, ')}. Fix: {next_step}")
    return left


def _skip_fix(result: str, repo: Path, story: str) -> str:
    """The one command that clears a skipped repair, from the reason `commit_after` gave."""
    rerun = f"then run `olivercode conform --fix --story {story} {repo}`"
    if "uncommitted changes" in result:
        return f"commit or stash those files in {repo} (`git -C {repo} status`), {rerun}"
    if "nothing to commit" in result:
        return f"run `git -C {repo} status` to see why the fix changed no file, {rerun}"
    if "no commits" in result:
        return f"make the first commit in {repo}, {rerun}"
    if "gates refused" in result:
        return f"read the refusal above, change what it names, {rerun}"
    if "a fix failed" in result:
        return f"run the failing command by hand to see its output, {rerun}"
    return f"run `git -C {repo} status` to see what is in the way, {rerun}"


def command_backlog_setup(argv: list[str]) -> int:
    """`olivercode backlog-setup [DIR] [--apply [--commit --story REF]]`: see lib/backlog_setup.py and docs/SETUP.md."""
    apply, rest = take_flag(argv, "--apply")
    commit, rest = take_flag(rest, "--commit")
    story = None
    if "--story" in rest and rest.index("--story") + 1 < len(rest):
        at = rest.index("--story")
        story, rest = rest[at + 1], rest[:at] + rest[at + 2:]
    if len(rest) > 1 or (rest and rest[0].startswith("-")) or (commit and not (apply and story)):
        print("Usage: olivercode backlog-setup [DIR] [--apply [--commit --story REF]]")
        return 1
    target = Path(rest[0] if rest else ".").expanduser()
    if target.is_dir() and _repo_state.skipped(target.resolve().name, target):
        return 0
    if not require_dir(target):
        return 1
    if not commit:
        return _backlog_setup.run_setup(target, apply, _backlog_setup.Api(), OC_ROOT)
    code: list[int] = []
    result = commit_after(target.resolve(), lambda: code.append(_backlog_setup.run_setup(target, apply, _backlog_setup.Api(), OC_ROOT)),
                          f"Set up the board config and hooks with backlog-setup ({story})", "The repo's backlog config and commit-msg hook now match the board.")
    print(f"  [COMMIT] {target.resolve().name}: {result}")
    return code[0] if code else 1


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
    _set_hooks_path(repo_path)


def _set_hooks_path(repo_path: Path) -> None:
    """Point git at the repo's .githooks, so every hook sync-hooks installs runs. A repo that already runs its own hooks folder keeps it."""
    if repo_profiles.own_hooks_path(repo_path):
        return
    subprocess.run(["git", "-C", str(repo_path), "config", "core.hooksPath", ".githooks"], check=True)


HOOK_FILES = ("pre-commit", "pre-commit-private", "pre-push", "commit-msg")  # every file a sync can write or delete


VALIDATE_PATH = "scripts/validate.sh"  # sync also inserts the validation-queue block here
MANAGED_PATHS = tuple(f".githooks/{n}" for n in HOOK_FILES) + (VALIDATE_PATH,)


def _migrate_to_global_hooks(repo_path: Path) -> None:
    """Remove a public repo's committed OliverCode hook copies and its local core.hooksPath=.githooks,
    so it relies on the machine's global default from `olivercode install` instead of a per-repo
    commit (#1154). A local hooksPath pointing anywhere else is left alone, since sync-hooks never set it."""
    hooks_dir = repo_path / ".githooks"
    for name in HOOK_FILES:
        (hooks_dir / name).unlink(missing_ok=True)
    if _git(repo_path, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ".githooks":
        _git(repo_path, "config", "--local", "--unset", "core.hooksPath")


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_path), *args], capture_output=True, text=True)


def _hook_snapshot(repo_path: Path) -> dict:
    """Each hook file's bytes and executable bit before sync runs, and whether git already saw it changed.

    A path whose git status is not empty (modified, staged, deleted or untracked) differs for a reason that
    is not sync's, so the commit step leaves that repo alone."""
    snap = {}
    status = _git(repo_path, "status", "--porcelain", "--untracked-files=all", "--", *MANAGED_PATHS).stdout.splitlines()
    changed = {line[3:].split(" -> ")[-1].strip('"') for line in status}
    for rel in MANAGED_PATHS:
        path = repo_path / rel
        snap[rel] = {"data": path.read_bytes() if path.is_file() else None,
                     "exec": path.is_file() and os.access(path, os.X_OK), "dirty": rel in changed}
    return snap


def _commit_synced(name: str, repo_path: Path, before: dict, story: str, archived: str | None = None) -> None:
    """Commit the hook files sync changed in one repo, by explicit path, and print one line about it.

    Never pushes and never skips the repo's own hooks: a refusal is reported and the paths are unstaged."""
    def say(text: str) -> None:
        print(f"  [COMMIT] {name}: {text}")

    state = archived or _repo_state.archived(repo_path)
    if state:
        return say(f"not committed, {state} on GitHub")
    if _git(repo_path, "rev-parse", "-q", "--verify", "HEAD").returncode != 0:
        return say("not committed, the repo has no commits")
    changed, already = [], []
    foreign = []  # uncommitted edits that sync overwrote, so they were not the template (#1032)
    for rel, was in before.items():
        path = repo_path / rel
        now = (path.read_bytes() if path.is_file() else None, path.is_file() and os.access(path, os.X_OK))
        differs = now != (was["data"], was["exec"])
        if differs and was["dirty"]:
            foreign.append(rel)
        elif differs:
            changed.append(rel)
        elif was["dirty"]:
            # Uncommitted but already in the state this run's install() produces, present or removed
            # (an earlier run wrote or deleted it and was never committed, #1154): sync leaves it, so commit it.
            already.append(rel)
    if foreign:  # put the owner's edits back, so a re-run asks again instead of committing the template over them
        for rel in foreign:
            path, was = repo_path / rel, before[rel]
            if was["data"] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(was["data"])
                path.chmod(0o755 if was["exec"] else 0o644)
        return say(f"not committed, {', '.join(foreign)} already had uncommitted changes that are not the template, so they are kept as they were. "
                   "Tell me whether those edits are yours, then commit or discard them and re-run")
    changed += already
    if not changed:
        return say("nothing to commit")
    queue_line = ("scripts/validate.sh now takes a slot in the per-user validation queue, so a script that calls it "
                  "directly waits its turn.\n\n" if VALIDATE_PATH in changed else "")
    message = (f"Sync the managed hook files from OliverCode ({story})\n\n"
               "The hook files in this repo now match the current OliverCode templates.\n\n" + queue_line +
               "No test: managed hook files copied from OliverCode\nSize: XS\n")
    say(commit_changes(repo_path, changed, message))


def _queue_block(oc_root: Path, name: str, repo_path: Path) -> None:
    """Insert the validation-queue block into the repo's own scripts/validate.sh when it lacks it."""
    line = _snippet.report(name, *_snippet.ensure_queue_snippet(oc_root, repo_path))
    if line:
        print(line)


def _sync_one(name: str, repo_path: Path, failed: list[str], install, ok_line: str, commit: bool, story: str | None) -> bool:
    """Run one repo's install, print `ok_line` and commit the change when asked; a repo whose git config fails is reported and the rest still sync."""
    before = _hook_snapshot(repo_path) if commit else {}
    try:
        install()
        print(ok_line)
        if commit:
            _commit_synced(name, repo_path, before, story)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  [FAIL] {name}: {exc}")
        failed.append(name)
        return False


def command_sync_hooks(oc_root: Path, fleet_root: Path | None = None, commit: bool = False, story: str | None = None) -> int:
    """Converge hooks + core.hooksPath across every fleet repo and every private repo.

    fleet_root defaults to OliverCode's parent (the sibling-repos layout). A fork whose
    repos live elsewhere passes --root; without that, every repo would silently SKIP as
    "not present on this machine" and the command would still report success.

    A public repo with no declared variant gets its committed hook files and its local
    core.hooksPath=.githooks removed (the old per-repo copy, #1154): `olivercode install`'s
    global core.hooksPath covers it instead, so a template change never costs that repo a
    commit. A private or declared-variant repo keeps its own committed hook, since the
    global default runs the public gates.

    With commit=True each repo's changed hook files are then committed by path under `story`
    (see _commit_synced). The default writes files and commits nothing.
    """
    if commit and not story:
        print("sync-hooks --commit needs --story REF, the story from your backlog that the commit cites.")
        return 1
    templates_dir = repo_gates.hook_templates(oc_root)
    fleet_root = fleet_root or oc_root.parent
    updated = 0
    skipped = 0
    failed_repos: list[str] = []

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
            if _sync_one(name, repo_path, failed_repos, lambda: (_install_pre_push(repo_path, templates_dir), _set_hooks_path(repo_path), _queue_block(oc_root, name, repo_path)),
                         f"  [SKIP] {name}: declared hook variant ({variant}) — pre-commit left untouched, pre-push and commit-msg synced, hooksPath set", commit, story):
                skipped += 1
            continue
        # A private repo keeps its own committed hook, which drops the PII gate (it holds
        # personal data by design): sync-hooks installs it directly, since the machine's
        # global default runs the public gates instead. A public repo with no variant holds
        # no OliverCode file at all any more; it relies on that global default (#1154).
        is_private = bool(profile.get("private"))
        if is_private:
            if _sync_one(name, repo_path, failed_repos, lambda: (_install_hook_pair(repo_path, templates_dir, private_repo=True), _queue_block(oc_root, name, repo_path)),
                         f"  [OK] {name}: private-variant hooks synced, hooksPath set", commit, story):
                updated += 1
        elif _sync_one(name, repo_path, failed_repos, lambda: (_migrate_to_global_hooks(repo_path), _queue_block(oc_root, name, repo_path)),
                       f"  [OK] {name}: hook files removed, the machine's global core.hooksPath covers it", commit, story):
            updated += 1

    for name, root in _private_repos().items():
        if (root / ".git").exists():
            if _repo_state.skipped(name, root):
                skipped += 1
                continue
            if _sync_one(name, root, failed_repos, lambda: (_install_hook_pair(root, templates_dir, private_repo=True), _queue_block(oc_root, name, root)),
                         f"  [OK] {name}: private-variant hook synced, hooksPath set", commit, story):
                updated += 1
        else:
            print(f"  [SKIP] {name}: no .git at {root}")
            skipped += 1

    print(f"\n{updated} target(s) synced, {skipped} skipped" + (f", {len(failed_repos)} failed: {', '.join(failed_repos)}." if failed_repos else "."))
    return 1 if failed_repos else 0


def command_update(oc_root: Path | None = None, story: str | None = None) -> int:
    """Pull this checkout's tracking branch, re-run install, converge fleet hooks, then run conform on the fleet.

    A dirty, mid-rebase or diverged checkout is refused before anything changes (update_state.py).

    Install runs on every update because a pull can add a skill or a Claude Code hook,
    and only install links those into ~/.claude; without it a second device kept the
    files of a new skill with no link to them. Install and sync-hooks run as new
    processes, so they use the code the pull just brought in, never the copy this
    process loaded before it.

    On a fork `origin` is the FORK, so this does not fetch upstream framework changes.
    Pulling those is a deliberate act with real merge consequences -- a fork carries local
    edits to CLAUDE.md, contracts, and templates, which is the whole point of forking -- so
    it is documented in docs/SETUP.md ("Staying current") and not automated here.

    With `story` the hook sync commits each repo's changed hooks under that story (sync-hooks --commit).
    """
    root = oc_root or OC_ROOT
    stuck = update_state.problem(root)
    if not stuck and update_state.rewritten(root):  # origin replaced commits this checkout holds (#1032)
        saved = update_state.realign(root)
        if not saved:
            print("olivercode update changed nothing: could not save the old main to a backup branch and realign.")
            return 1
        print(f"origin's history was rewritten. The old main is saved on branch {saved[0]}, and this checkout now matches {saved[1]}.")
    if stuck:
        what, fix = stuck
        print(f"olivercode update changed nothing: {what}.")
        print(f"Fix: {fix}")
        return 1
    pull_code = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"]).returncode
    if pull_code != 0:
        return pull_code
    launcher = [sys.executable, str(root / "scripts" / "olivercode")]
    install_code = subprocess.run([*launcher, "install"]).returncode
    sync_code = subprocess.run([*launcher, "sync-hooks", *(["--commit", "--story", story] if story else [])]).returncode
    conform_code = subprocess.run([*launcher, "conform"]).returncode
    if conform_code:
        print("Conform found failures in the fleet. Each Fix line above names the repair; `olivercode conform --fix --story N` applies the ones it can.")
    return install_code or sync_code or conform_code
