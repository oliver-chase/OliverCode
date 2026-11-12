"""Command-line plumbing shared by the launcher and the command modules: the command list, the usage text and argument helpers."""

from __future__ import annotations

import sys
from pathlib import Path


COMMANDS = [
    ("olivercode bootstrap DIR [--dry-run]", "Stamp the project template into a repo, per the bootstrap manifest"),
    ("olivercode size [DIR] [--lower]", "Print a repo's total lines, its docs/SIZE-BASELINE.json baseline and the headroom. --lower rewrites the baseline to the current total when that is no higher, and refuses to raise it"),
    ("olivercode backlog-setup [DIR] [--apply]", "Set up or repair a repo's GitHub Project board, backlog config and commit-msg hook. Dry run unless --apply"),
    ("olivercode discover --root DIR [--register]", "Scan for git repos and report what governance they already have. --register adds the new ones to the registry with the validation command each repo names"),
    ("olivercode install", "Symlink CLAUDE.md, VOICE.md + skills into ~/.claude and add its hooks to settings.json (backs up anything it replaces)"),
    ("olivercode uninstall", "Remove the links and settings.json hooks install wrote, restoring what it backed up"),
    ("olivercode conform [DIR] [--root DIR] [--offline] [--hooks-only]", "Check a repo, or every registered repo, against docs/CONTRACT.md. Prints pass, fail, exception, manual or skip per requirement with the fix command, and exits non-zero on any fail. --offline skips the checks that call GitHub, and --hooks-only checks only that git runs the gates"),
    ("olivercode place", "Check that every repo, worktree and backup on this machine lives under repoRoot (olivercode.local.json). Exits non-zero on any stray and names the fix"),
    ("olivercode clean [--apply]", "List the worktrees that are merged and clean and so reclaimable, and the ones kept with the reason. --apply removes the reclaimable ones with git worktree remove"),
    ("olivercode policy init [DIR]", "Write the default permission policy (.olivercode/policy.json) into a repo. The policy_guard hook then denies commands and paths outside it and asks the owner at a push, a mass delete or a third failed gate"),
    ("olivercode gh-limit [clear]", "Show whether the shared GitHub rate-limit hold is on and until when. clear lifts the hold early"),
    ("olivercode health [--root DIR]", "Run health checks on this machine: Claude Code hooks, skill links, voice copies, remotes and file sizes"),
    ("olivercode update", "Pull this checkout's tracking branch, re-run install, then sync fleet hooks"),
    ("olivercode sync-hooks [--root DIR]", "Converge hooks + core.hooksPath across the fleet and the private repos"),
    ("olivercode audit-fleet", "Run the audit skill's structure check, which includes the description cap, against this machine's skills folder + OliverCode's own skills"),
    ("olivercode skills [--grep TERM]", "List every skill in skills/, optionally filtered by name/description"),
    ("olivercode maintain [--fix | --schedule | --unschedule]", "Check this machine and repair what is safe: dangling links, dead worktrees, iCloud-evicted git files. --schedule runs it daily"),
    ("olivercode report [--days N]", "Print how many times each gate blocked a commit in the last N days"),
    ("olivercode guide", "Print a plain-language overview: first steps, every command, and every skill with the phrases that load it"),
]


def print_usage() -> None:
    print("OliverCode Terminal Launcher\n")
    print("Commands:")
    for cmd, desc in COMMANDS:
        print(f"  {cmd:<32} {desc}")
    print("\nNew here? Run: olivercode guide")


def take_root_flag(argv: list[str]) -> tuple[Path | None, list[str]]:
    """Pull `--root <dir>` out of argv. Returns (root or None, remaining args)."""
    if "--root" not in argv:
        return None, argv
    idx = argv.index("--root")
    if idx + 1 >= len(argv):
        print("Error: --root requires a directory.")
        sys.exit(1)
    root = Path(argv[idx + 1]).expanduser()
    if not root.is_dir():
        print(f"Error: --root {root} is not a directory.")
        sys.exit(1)
    return root, argv[:idx] + argv[idx + 2:]


def take_flag(argv: list[str], flag: str) -> tuple[bool, list[str]]:
    """Pull a bare flag such as `--dry-run` out of argv. Returns (whether it was there, the remaining args)."""
    return flag in argv, [a for a in argv if a != flag]


def require_dir(path: Path) -> bool:
    """True when `path` is a directory; otherwise prints the launcher's one error line and returns False."""
    if path.is_dir():
        return True
    print(f"Error: {path} is not a directory.")
    return False


def reject_extra(cmd: str, rest: list[str]) -> None:
    """Unknown arguments must fail loudly.

    Rejecting them beats ignoring them: `sync-hooks --root /somewhere` would otherwise
    sync the DEFAULT fleet and print "6 targets synced", giving a fork with a different
    layout a success message for work done on the wrong repos.
    """
    if rest:
        print(f"Error: unexpected argument(s) for '{cmd}': {' '.join(rest)}")
        print_usage()
        sys.exit(1)
