#!/usr/bin/env python3
"""Claude Code SessionStart hook: tells the session, once, what would silently fail here.

`olivercode conform` only sees the repos in its registry and only when someone runs it.
This runs in every session, in whatever folder it starts, and names these gaps:

- the repo ships commit gates but git is not pointed at them (commits will be refused
  by commit_guard until it is fixed, so the session learns the fix up front)
- the repo is a git repo with no commit gates of its own
- a link that loads OliverCode's rules into ~/.claude is broken
- a repo, worktree or backup sits outside repoRoot (scripts/lib/placement.py)
- the OliverCode checkout holds commits origin/main lacks, or trails it with edits (the fast-forward and the board groom belong to `olivercode maintain --fix`)

In a repo that has commit gates, a session that is not headless prints one line: the open count and the story building. The count comes from the status
digest when it is under DIGEST_TTL old, and from a fresh read of GitHub when it is not (#985, #1017). The line tells the session nothing to read.

It prints nothing else when nothing is wrong, so a healthy session pays no context for it.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
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


def status_line(cwd: Path) -> list[str]:
    """The one session-start line for a governed repo: its open count and the story building (#985, #992, #1017). The count comes from the status digest
    when that is under DIGEST_TTL old, so a session that starts soon after another calls no GitHub. Nothing in a headless builder, an ungoverned folder or
    a failed read."""
    if headless():
        return []
    try:
        root = repo_gates.repo_root(cwd)
        if not root or not repo_gates.has_gates(root):
            return []
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import cmd_status, repo_state, run_lock
        slug = repo_state.origin(root)
        if not slug:
            return []
        now = datetime.now(timezone.utc)
        open_now = cmd_status.cached_open(slug, now)
        if open_now is None:
            done = cmd_status.write_digest(slug, out=lambda _text: None)
            if done is None:
                return []
            open_now = done[2]
        held = run_lock.active(slug, now.timestamp())
    except Exception as exc:  # noqa: BLE001 -- a digest bug never blocks a session
        print(f"session_check: status line failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    building = ", ".join(f"#{n}" for n in held.get("building") or []) if held else ""
    state = f"building {building}" if building else "none building"
    return [f"{slug}: {open_now} open stories, {state}." + (" A request joins the queue as a story." if held else "")]


# shortcut: digest_notes and run_notes are no longer called by the hook (status_line replaced them); tests outside story #1017's Files area still exercise them, so delete them with those tests.
def digest_notes(cwd: Path) -> list[str]:
    """The three session-start lines from a refreshed status digest, or nothing in a headless builder, an ungoverned folder or a failed read (#985)."""
    if headless():
        return []
    try:
        root = repo_gates.repo_root(cwd)
        if not root or not repo_gates.has_gates(root):
            return []
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import cmd_status, repo_state
        done = cmd_status.write_digest(repo_state.origin(root), out=lambda _text: None)
    except Exception as exc:  # noqa: BLE001 -- a digest bug never blocks a session
        print(f"session_check: status digest failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return done[2] if done else []


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
        from lib import main_checkout, maintain
        ahead = main_checkout.ahead_refusal(maintain.OC_ROOT) or main_checkout.stale_refusal(maintain.OC_ROOT)  # names the commits an ahead checkout holds, with the command that moves them (#785)
    except Exception as exc:  # noqa: BLE001 -- never blocks a session
        print(f"session_check: checkout fast-forward failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return [ahead] if ahead else []


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
    parts = (["OliverCode session check: " + " ".join(found)] if found else []) + status_line(cwd)
    if parts:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(parts)}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop a session from starting
        print(f"session_check failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
