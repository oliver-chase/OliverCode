"""The main checkout of a fleet repo holds only landed work (#664).

`reason` is the pretool guard: an edit or commit in the main checkout is refused. `drift` is the check `olivercode health` and the
nightly job run: it names a main checkout that is ahead of origin, mid-rebase or holds conflict markers, each with its fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lib import update_state
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")  # the tools that change a file
from lib.local_config import OC_ROOT
from lib.repo_profiles import iter_fleet, load_repo_profiles

MARKERS = r"^(<<<<<<<|>>>>>>>) "


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)


def fleet_roots() -> list[Path]:
    profiles = load_repo_profiles(OC_ROOT)[0]
    return [OC_ROOT.resolve(), *(p.resolve() for _n, _pr, p in iter_fleet(profiles, OC_ROOT.parent, skip_archived=False))]


def is_main_checkout(root: Path | None) -> bool:
    """A fleet repo's own checkout, not one of its linked worktrees."""
    return bool(root) and (root / ".git").is_dir() and root.resolve() in fleet_roots()


def _shell_writes(command: str, cwd: Path) -> list[Path]:
    """The files a command writes: redirect targets, tee, cp, mv, touch and `sed -i` files, read from the parsed
    command words so quoted text and comments name nothing."""
    from lib import policy
    found: list[Path] = []
    try:
        for words in policy.lex_uncommented(command):
            name, rest = policy._head(words)
            found += [cwd / Path(t).expanduser() for t in policy._write_targets(name, rest) if t and not t.startswith("&")]
    except ValueError:
        return []
    return [t for t in found if not str(t).startswith("/dev/")]


def reason(data: dict) -> str:
    """The refusal for an edit or commit made in the main checkout of a fleet repo, or an empty string."""
    import commit_guard
    import repo_gates
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or ".")
    command = tool_input.get("command") or ""
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if path and data.get("tool_name") in EDIT_TOOLS:
        wheres = [(Path(path).parent if Path(path).is_absolute() else cwd, path)]
    elif command:
        wheres = [(w, "") for w, *_ in commit_guard._commits(command, cwd)] + [(t.parent, str(t)) for t in _shell_writes(command, cwd)]
        if not wheres:
            return ""
    else:
        return ""
    for where, path in wheres:
        while not where.is_dir() and where != where.parent:
            where = where.parent
        root = repo_gates.repo_root(where)
        if is_main_checkout(root):
            if path and Path(path).resolve().is_relative_to(root.resolve() / ".claude-optimization") and _git(root, "check-ignore", "-q", path).returncode == 0:
                continue
            return (f"Refused: {root.name}'s main checkout holds only landed work. Run `git worktree add -b story/N ../_worktrees/oc-N origin/main` to work in a worktree, "
                    "then `olivercode land WORKTREE STORY` to put the commit on origin/main.")
    return ""


def ahead_refusal(root: Path) -> str:
    """The commits a checkout holds that origin/main lacks, each with its author, and the one command that moves them to a branch;
    empty when it holds none. The SessionStart check, `olivercode health`, `update` and `complete_story` all say this (#785)."""
    if (_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout or "").strip() != "main":  # a worktree's story branch is ahead by design (#785)
        return ""
    commits = update_state.ahead_commits(root)
    if not commits:
        return ""
    behind = int(_git(root, "rev-list", "--count", "HEAD..origin/main").stdout.strip() or 0)
    diverged = f" and trails it by {behind}, so a merged fix cannot reach it and the old hooks keep running (#823)" if behind else ""
    return (f"{root.name} holds {len(commits)} commit(s) that origin/main lacks{diverged}: {'; '.join(commits)}. "
            f"Run `{update_state.ahead_fix(root)}` to move them to a local branch and leave the checkout level with origin/main")


def stale_refusal(root: Path) -> str:
    """The reason a checkout behind origin/main cannot fast-forward (edited or off main), with its fix, or empty (#823).
    A diverged checkout is named by ahead_refusal."""
    from lib import maintain
    if (root / ".git").is_file():  # a story worktree sits off main by design and is never the installed checkout
        return ""
    behind, state = maintain.main_checkout_lag(root)
    if not behind or state in ("clean", "unknown", "diverged"):
        return ""
    head = f"{root.name} trails origin/main by {behind} commit(s) and is {state}, so it cannot fast-forward and the merged fixes are not live. "
    if state == "off main":
        return head + f"Run `git -C {root} checkout main`, then `olivercode update`"
    return head + "Commit the edits to a branch or discard them, then run `olivercode update`"


def drift(root: Path) -> list[str]:
    """One line per way this main checkout has drifted from origin/main, each with its fix. Reads only refs already fetched."""
    if not (root / ".git").is_dir():
        return []
    lines = []
    for found in (ahead_refusal(root), stale_refusal(root)):
        if found:
            lines.append(found)
    for folder in ("rebase-merge", "rebase-apply"):
        if (root / ".git" / folder).is_dir():
            if subprocess.run(["pgrep", "-x", "git"], capture_output=True).returncode == 0:
                lines.append(f"{root.name}'s main checkout is mid-rebase. Finish it with `git rebase --continue`, or run `git rebase --abort`")
            else:
                lines.append(f"{root.name}'s main checkout has a stale {folder} folder and no git process runs. Run `git -C {root} rebase --abort`, or delete .git/{folder} when that fails")
    marked = _git(root, "grep", "-lE", MARKERS)
    if marked.returncode == 0 and marked.stdout.strip():
        files = marked.stdout.split()
        lines.append(f"{root.name}'s main checkout holds conflict markers in {', '.join(files[:3])}. Resolve them, or restore a file with `git -C {root} checkout -- FILE`")
    return lines
