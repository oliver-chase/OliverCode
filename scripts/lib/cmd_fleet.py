"""Launcher commands that act on OliverCode and its private repos: backlog-setup, sync-hooks and update."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lib import backlog_setup as _backlog_setup
from lib import repo_gates, repo_profiles
from lib import update_state
from lib.cli import require_dir, take_flag
from lib.gitfiles import commit_after, commit_changes
from lib.local_config import OC_ROOT
from lib import repo_state as _repo_state
from lib.local_config import private_repos as _private_repos
from lib import gitfiles


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


MANAGED_PATHS = tuple(f".githooks/{n}" for n in HOOK_FILES)


def _hook_snapshot(repo_path: Path) -> dict:
    """Each hook file's bytes and executable bit before sync runs, and whether git already saw it changed.

    A path whose git status is not empty (modified, staged, deleted or untracked) differs for a reason that
    is not sync's, so the commit step leaves that repo alone."""
    snap = {}
    status = gitfiles.run(repo_path, "status", "--porcelain", "--untracked-files=all", "--", *MANAGED_PATHS).stdout.splitlines()
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
    if gitfiles.run(repo_path, "rev-parse", "-q", "--verify", "HEAD").returncode != 0:
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
        elif was["dirty"] and path.is_file():
            already.append(rel)  # uncommitted but already equal to the template: sync leaves it, so commit it
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
    message = (f"Sync the managed hook files from OliverCode ({story})\n\n"
               "The hook files in this repo now match the current OliverCode templates.\n\n"
               "No test: managed hook files copied from OliverCode\nSize: XS\n")
    say(commit_changes(repo_path, changed, message))


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


def command_sync_hooks(oc_root: Path, commit: bool = False, story: str | None = None) -> int:
    """Converge hooks + core.hooksPath in every private repo (OliverCode itself is not walked).

    With commit=True each repo's changed hook files are then committed by path under `story`
    (see _commit_synced). The default writes files and commits nothing.
    """
    if commit and not story:
        print("sync-hooks --commit needs --story REF, the story from your backlog that the commit cites.")
        return 1
    templates_dir = repo_gates.hook_templates(oc_root)
    updated = 0
    skipped = 0
    failed_repos: list[str] = []

    for name, root in _private_repos().items():
        if (root / ".git").exists():
            if _repo_state.skipped(name, root):
                skipped += 1
                continue
            if _sync_one(name, root, failed_repos, lambda: _install_hook_pair(root, templates_dir, private_repo=True),
                         f"  [OK] {name}: private-variant hook synced, hooksPath set", commit, story):
                updated += 1
        else:
            print(f"  [SKIP] {name}: no .git at {root}")
            skipped += 1

    print(f"\n{updated} target(s) synced, {skipped} skipped" + (f", {len(failed_repos)} failed: {', '.join(failed_repos)}." if failed_repos else "."))
    return 1 if failed_repos else 0


def command_update(oc_root: Path | None = None, story: str | None = None) -> int:
    """Pull this checkout's tracking branch, re-run install, sync the hooks of OliverCode's private repos.

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
    return install_code or sync_code
