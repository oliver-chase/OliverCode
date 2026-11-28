#!/usr/bin/env python3
"""Claude Code SessionStart hook: tells the session, once, what would silently fail here.

`olivercode health` only sees OliverCode and its private repos, and only when someone runs it.
This runs in every session, in whatever folder it starts, and names these gaps:

- the repo ships commit gates but git is not pointed at them (commits will be refused
  by commit_guard until it is fixed, so the session learns the fix up front)
- the repo is a git repo with no commit gates of its own
- a link that loads OliverCode's rules into ~/.claude is broken
- a repo, worktree or backup sits outside repoRoot (scripts/lib/placement.py)
- the OliverCode checkout holds commits origin/main lacks, or trails it with edits (the fast-forward belongs to `olivercode maintain --fix`)

In a repo that has commit gates, a session that is not headless also refreshes the status digest with no model call and prints three lines: the open
count, the last story landed and the digest to read before acting (#985).

It prints nothing else when nothing is wrong, so a healthy session pays no context for it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import gitfiles  # noqa: E402
import repo_gates  # noqa: E402

RULE_LINKS = ("CLAUDE.md", "VOICE.md", "DESIGN.md")


def notes(cwd: Path, claude_dir: Path, session_id: str = "") -> list[str]:
    out = []
    for name in RULE_LINKS:
        link = claude_dir / name
        if link.is_symlink() and not link.exists():
            out.append(f"~/.claude/{name} is a broken link, so OliverCode's rules did not load. "
                       "Run `scripts/olivercode install` from the OliverCode folder.")
    out += ([] if headless() else placement_notes()) + gh_notes() + checkout_notes()
    root = repo_gates.repo_root(cwd)
    if root:
        if repo_gates.has_gates(root):
            problem = repo_gates.gate_problem(root)
            if problem:
                out.append(f"In {root.name}, the gates are not running: {problem}. Commits are refused until it is fixed. "
                           f"Run `{repo_gates.fix_command(root)}`" + ("" if (root / ".git").is_file() else ", or `olivercode sync-hooks` for a fleet repo") + ".")
        else:
            out.append(f"{root.name} has no commit gates of its own (no .githooks/pre-commit), "
                       "so nothing checks a commit here for secrets or broken rules.")
    return out


def headless() -> bool:
    """True inside a session that run_cli started. A builder starts near its token budget, so it skips the placement scan (#911)."""
    return os.environ.get("OLIVERCODE_HEADLESS") == "1"  # model.HEADLESS_ENV


def digest_notes(cwd: Path) -> list[str]:
    """The three session-start lines from the last status digest, or nothing in a headless builder, an ungoverned folder or a failed read (#985).
    The digest's GitHub reads take seconds, so a detached `olivercode status digest` rewrites it and the hook never waits on it."""
    if headless():
        return []
    try:
        root = repo_gates.repo_root(cwd)
        if not root or not repo_gates.has_gates(root):
            return []
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import cmd_status, repo_state
        slug, path = repo_state.origin(root), cmd_status.digest_path()
        board = next((line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("Board: ")), "") if path.is_file() else ""
        detach([sys.executable, str(Path(__file__).resolve().parent.parent / "olivercode"), "status", "digest", "--root", str(root)])
        open_now = board.removeprefix(f"Board: {slug}: ").split(" open", 1)[0]  # a digest of another repo names another slug, so it gives no count
        return cmd_status.session_lines(slug, int(open_now), cmd_status.run_log(), path) if open_now.isdigit() else []
    except Exception as exc:  # noqa: BLE001 -- a digest bug never blocks a session
        print(f"session_check: status digest failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []


def run_notes(cwd: Path) -> list[str]:
    """One line while a run is active in this repo: the story in flight, and that requests are filed as stories and join the queue (#992)."""
    if headless():
        return []
    try:
        root = repo_gates.repo_root(cwd)
        if not root:
            return []
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import repo_state, run_lock
        slug = repo_state.origin(root)
        rec = run_lock.active(slug) if slug else {}
    except Exception as exc:  # noqa: BLE001 -- never blocks a session
        print(f"session_check: run lock check failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    if not rec:
        return []
    building = ", ".join(f"#{n}" for n in rec.get("building") or [])
    return [f"A run is active in {root.name}, {'building ' + building if building else 'building nothing yet'}. "
            "Start no builder here. A request that changes files is filed as a story and joins the queue."]


def placement_notes() -> list[str]:
    """One note naming the repos, worktrees and backups outside repoRoot, or nothing."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import placement
        stray = placement.findings()
    except Exception as exc:  # noqa: BLE001 -- a placement bug never blocks a session
        print(f"session_check: placement check failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    if not stray:
        return []
    names = ", ".join(f"{f.path.name} ({f.kind})" for f in stray[:5]) + (f" and {len(stray) - 5} more" if len(stray) > 5 else "")
    return [f"{len(stray)} repo/worktree/backup item(s) sit outside repoRoot: {names}. "
            "Run `olivercode place` for the fix for each, and `olivercode clean` for merged worktrees."]


def checkout_notes() -> list[str]:
    """Names an OliverCode checkout that holds commits origin/main lacks (#785); runs no git merge, since scheduled maintenance does the fast-forward (#901)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import main_checkout
        from lib.local_config import OC_ROOT
        ahead = main_checkout.ahead_refusal(OC_ROOT) or main_checkout.stale_refusal(OC_ROOT)  # names the commits an ahead checkout holds, with the command that moves them (#785)
    except Exception as exc:  # noqa: BLE001 -- never blocks a session
        print(f"session_check: checkout fast-forward failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return ([ahead] if ahead else []) + update_notes()


STALE_FETCH_SECONDS = 24 * 60 * 60


def update_notes(root: Path | None = None) -> list[str]:
    """One line when this checkout trails its upstream branch by its local refs (#1285). It never waits on the network:
    a fetch older than a day starts one detached `git fetch`, tried at most once a day, and the next session sees its result."""
    if headless():
        return []
    try:
        root = root or Path(__file__).resolve().parent.parent.parent
        behind = gitfiles.run(root, "rev-list", "--count", "HEAD..@{upstream}", timeout=3)  # fails with no upstream or a detached HEAD
        if behind.returncode or gitfiles.run(root, "status", "--porcelain", "--untracked-files=no", timeout=3).stdout.strip():
            return []
        git_dir = gitfiles.out(root, "rev-parse", "--git-dir", timeout=3).strip()
        if git_dir:
            _fetch_if_stale(root, root / git_dir / "FETCH_HEAD")
        count = int(behind.stdout)
    except Exception as exc:  # noqa: BLE001 -- never blocks a session
        print(f"session_check: update check failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return [f"{count} OliverCode update{' is' if count == 1 else 's are'} available. Run `olivercode update`."] if count > 0 else []


def _fetch_if_stale(root: Path, fetch_head: Path) -> None:
    """Start one background fetch when the last fetch and the last attempt are both over a day old."""
    import failure_log
    stamp = failure_log.home() / "update-fetch-attempt"
    now = time.time()
    for path in (fetch_head, stamp):
        if path.exists() and now - path.stat().st_mtime < STALE_FETCH_SECONDS:
            return
    stamp.touch()
    start_fetch(root)


def start_fetch(root: Path) -> None:
    detach(["git", "-C", str(root), "fetch", "--quiet"])


def detach(argv: list[str]) -> None:
    """Start one command that outlives the hook; the hook never waits on it."""
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def gh_notes() -> list[str]:
    """A note while the shared GitHub rate-limit hold is on, else nothing."""
    try:
        import gh_budget
        why = gh_budget.refusal()
    except Exception as exc:  # noqa: BLE001 -- never blocks a session
        print(f"session_check: rate-limit note failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return [why] if why else []


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    cwd = Path(data.get("cwd") or ".")
    found = notes(cwd, Path.home() / ".claude", str(data.get("session_id") or ""))
    parts = (["OliverCode session check: " + " ".join(found)] if found else []) + run_notes(cwd) + digest_notes(cwd)
    if parts:
        print(json.dumps(payload(parts, found)))
    return 0


def payload(parts: list[str], found: list[str]) -> dict:
    """The hook's output: every note goes to the session as context, and the update line also goes to the user as a system message,
    since context alone reaches only the model (#1285)."""
    out: dict = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(parts)}}
    update = next((n for n in found if "`olivercode update`" in n), "")
    if update:
        out["systemMessage"] = update
    return out


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop a session from starting
        print(f"session_check failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
