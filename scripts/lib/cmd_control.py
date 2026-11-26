"""Owner controls for a running drain: pause, resume and cancel one story (#1214)."""
from __future__ import annotations

from lib import run_lock
from lib.cmd_drain import resolve_repo
from lib.cmd_dispatch import origin_slug
from lib.local_config import backlog_config


USAGE = "Usage: olivercode pause REPO | resume REPO | cancel REPO STORY"


def _repo(name: str):
    repo = resolve_repo(name)
    if repo is None:
        print(f"Refused: {name} is not a repo with docs/backlog-config.json.")
        return None, ""
    cfg = backlog_config(repo)
    slug = origin_slug(repo, f"{cfg['repoOwner']}/{cfg['repoName']}")
    return repo, slug


def command_control(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or argv[0] not in ("pause", "resume", "cancel"):
        print(USAGE)
        return 2
    action, name = argv[:2]
    repo, slug = _repo(name)
    if repo is None:
        return 1
    if action == "cancel":
        if len(argv) != 3 or not argv[2].isdigit() or int(argv[2]) < 1:
            print(USAGE)
            return 2
        story = int(argv[2])
        if not run_lock.request_cancel(slug, story):
            print(f"Nothing written: story #{story} is not currently building in {slug}.")
            return 0
        print(f"Cancellation requested for #{story}. It will stop after its current model session, keep the worktree, and return the card to Backlog without landing.")
        return 0
    if len(argv) != 2:
        print(USAGE)
        return 2
    if action == "pause":
        run_lock.pause(slug)
        holder = run_lock.active(slug)
        if holder:
            run_lock.set_paused(slug, holder.get("pid", -1), True)
        print(f"Paused {slug}. Existing builders finish their current story; no new story will be claimed.")
        return 0
    changed = run_lock.resume(slug)
    holder = run_lock.active(slug)
    if holder:
        run_lock.set_paused(slug, holder.get("pid", -1), False)
    print(f"Resumed {slug}." if changed else f"{slug} was not paused; no change.")
    return 0
