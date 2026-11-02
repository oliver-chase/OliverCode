"""Command-line plumbing shared by the launcher and the command modules: the command list, the usage text and argument helpers."""

from __future__ import annotations

import sys
from pathlib import Path


COMMANDS = [
    ("olivercode bootstrap DIR [--dry-run]", "Stamp the project template into a repo, per the bootstrap manifest"),
    ("olivercode size [DIR] [--lower]", "Print a repo's total lines, its docs/SIZE-BASELINE.json baseline and the headroom. --lower rewrites the baseline to the current total when that is no higher, and refuses to raise it"),
    ("olivercode backlog-setup [DIR] [--apply]", "Set up or repair a repo's GitHub Project board, backlog config and commit-msg hook. Dry run unless --apply"),
    ("olivercode discover --root DIR", "Scan for git repos and report what governance they already have"),
    ("olivercode install", "Symlink CLAUDE.md, VOICE.md + skills into ~/.claude and add its hooks to settings.json (backs up anything it replaces)"),
    ("olivercode uninstall", "Remove the links and settings.json hooks install wrote, restoring what it backed up"),
    ("olivercode conform [DIR] [--root DIR] [--offline]", "Check a repo, or every registered repo, against docs/CONTRACT.md. Prints pass, fail, exception, manual or skip per requirement with the fix command, and exits non-zero on any fail. --offline skips the checks that call GitHub"),
    ("olivercode health [--root DIR]", "Run health checks on this machine: Claude Code hooks, skill links, voice copies, remotes and file sizes"),
    ("olivercode update", "Pull this checkout's tracking branch, re-run install, then sync fleet hooks"),
    ("olivercode sync-hooks [--root DIR]", "Converge hooks + core.hooksPath across the fleet and the private repos"),
    ("olivercode audit-fleet", "Run the audit skill's structure check, which includes the description cap, against this machine's skills folder + OliverCode's own skills"),
    ("olivercode skills [--grep TERM]", "List every skill in skills/, optionally filtered by name/description"),
]


def print_usage() -> None:
    print("OliverCode Terminal Launcher\n")
    print("Commands:")
    for cmd, desc in COMMANDS:
        print(f"  {cmd:<32} {desc}")


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
