"""Command-line plumbing shared by the launcher and the command modules: the command list, the usage text and argument helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The oldest Python the code runs on. The tests use unittest's enterContext (3.11), and the
# suite is run and passes on 3.12. Health, the launcher and the install fix text all read this one value.
MIN_PYTHON = (3, 12)
MIN_PYTHON_TEXT = ".".join(map(str, MIN_PYTHON))
# The oldest gh whose `api --paginate --slurp` the code calls (2.48).
MIN_GH = (2, 48)
MIN_GH_TEXT = ".".join(map(str, MIN_GH))
if sys.platform == "darwin":
    PYTHON_FIX = f"brew install python@{MIN_PYTHON_TEXT}, then put its bin folder first on PATH (brew --prefix python@{MIN_PYTHON_TEXT})/libexec/bin"
    GH_FIX = "brew upgrade gh"
else:
    PYTHON_FIX = (f"sudo apt install python{MIN_PYTHON_TEXT} (Debian or Ubuntu) or sudo dnf install python{MIN_PYTHON_TEXT} (Fedora), "
                  f"then put python{MIN_PYTHON_TEXT} first on PATH")
    GH_FIX = "update gh from https://github.com/cli/cli/blob/trunk/docs/install_linux.md"


def gh_version(run=subprocess.run) -> tuple[int, int] | None:
    """The (major, minor) of the installed gh, or None when it is missing or unreadable."""
    try:
        text = run(["gh", "--version"], capture_output=True, text=True, timeout=10).stdout
        found = re.search(r"gh version (\d+)\.(\d+)", text)
        return (int(found.group(1)), int(found.group(2))) if found else None
    except (OSError, subprocess.SubprocessError):
        return None


def gh_problem(run=subprocess.run) -> str | None:
    """Why the installed gh is too old, or None when it is new enough or absent (a missing gh has its own message)."""
    found = gh_version(run)
    if found is None or found >= MIN_GH:
        return None
    return f"gh is {found[0]}.{found[1]} and OliverCode needs {MIN_GH_TEXT} or newer for `--paginate --slurp`: {GH_FIX}"


_SEARCH_DIRS = ("/opt/homebrew/bin", "/opt/homebrew/opt/python@3.12/libexec/bin", "/usr/local/bin")


def python_version(exe: str) -> tuple[int, int] | None:
    """The (major, minor) of an interpreter, or None when it does not run."""
    try:
        out = subprocess.run([exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=10).stdout.split()
        return int(out[0]), int(out[1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def newer_python() -> str | None:
    """A python3 at the minimum or newer, found on PATH and in the usual install folders, or None."""
    names = [f"python3.{m}" for m in range(20, MIN_PYTHON[1] - 1, -1)] + ["python3"]
    dirs = os.environ.get("PATH", "").split(os.pathsep) + list(_SEARCH_DIRS)
    for name in names:
        for d in dirs:
            exe = shutil.which(name, path=d) if d else None
            if exe and (python_version(exe) or (0, 0)) >= MIN_PYTHON:
                return exe
    return None


COMMANDS = [
    ("olivercode bootstrap DIR [--dry-run]", "Stamp the project template into a repo, per the bootstrap manifest"),
    ("olivercode backlog-setup [DIR] [--apply]", "Set up or repair a repo's GitHub Project board, backlog config, owner-action and program labels and commit-msg hook. Dry run unless --apply"),
    ("olivercode discover --root DIR", "Scan for git repos and report what governance they already have"),
    ("olivercode install", "Symlink CLAUDE.md, VOICE.md, DESIGN.md + skills into ~/.claude and add its hooks to settings.json (backs up anything it replaces)"),
    ("olivercode uninstall", "Remove the links and settings.json hooks install wrote, restoring what it backed up"),
    ("olivercode place", "Check that every repo, worktree and backup on this machine lives under repoRoot (olivercode.local.json). Exits non-zero on any stray and names the fix"),
    ("olivercode commit-check FILE_OR_TEXT", "Run the commit-msg gate on a draft message in this repo and print every finding at once: each blocking one and each voice warning. It exits non-zero on a blocking finding, commits nothing, queues no card and logs no refusal. Run it before git commit"),
    ("olivercode worktree add N | fix [PATH]", "add creates story N's worktree from origin/main under _worktrees, sets core.hooksPath for that worktree, builds the hooks and links the virtualenv, so its first commit passes. fix does the same for a worktree made with git worktree add. A builder subagent needs no config step"),
    ("olivercode clean [--apply]", "List the worktrees that are merged and clean and so reclaimable, and the ones kept with the reason. --apply removes the reclaimable ones with git worktree remove"),
    ("olivercode policy init [DIR]", "Write the default permission policy (.olivercode/policy.json) into a repo. The policy_guard hook then denies commands and paths outside it and asks first at a push or a mass delete, which the runner leaves for the owner"),
    ("olivercode validated record|check SHA", "Record a passing full validation of the working tree in ~/.olivercode/validated.jsonl, or check that a commit's tree has one under 7 days old. The pre-push hook refuses a push to main without it; OLIVERCODE_ALLOW_UNVALIDATED_PUSH=1 overrides"),
    ("olivercode gh-limit [clear|report|replay|--schedule|--unschedule|queue -- gh ...]", "Show whether the shared GitHub rate-limit hold is on and until when. clear lifts the hold early, report shows what each session spent, queue holds a gh command for the reset and replay or --schedule runs the queue"),
    ("olivercode board fit|sync [FLAGS]", "Everything that reads or repairs a fleet board, with no model call. fit BODY_FILE --title TITLE --config FILE adds a Related line to a story body for each open story whose Files area overlaps and names each Files area path that is not on main and that no Creates line names, and it changes no issue. sync moves the card of a closed issue to Status Complete and adds each open issue with no card through batch_project.py, because GitHub has no API for the built-in board workflows (--dry-run reports without writing). sync takes --schedule or --unschedule and runs every thirty minutes through launchd"),
    ("olivercode run \"TASK\" [--max-turns N] [--model NAME]", "Run Claude Code headless on a task in the current repo, then run the repo's own validation and send each failure back for another round until validation passes, two rounds in a row fail the same way or the spend reaches the $12 backstop. It uses the signed-in claude command, so no API key and no per-token billing are involved"),
    ("olivercode dispatch N [--from SID] [--dry-run]", "Build story N in one fresh headless session through the same code drain uses: refuse a closed, claimed or over-load case, claim it, build in its worktree, validate and land the commit, comment, close the story and release the claim"),
    ("olivercode drain REPO [--parallel N] [--foreground]", "Start a detached process, with its log under the OliverCode home, that works a repo's open stories until none remain: REST-list them (epics, claimed and owner-gated skipped), P0 first, start builders up to the machine-wide limit (`maxBuilders`, or exactly N with `--parallel N`) and never two on the same files, drive each through run, validate and `olivercode land`, restart a builder once and only after a crash or a timeout, and comment the reason on a story that stops. Ends with one summary line and a run-end row in the run log. Closing the chat or terminal does not stop it; `--foreground` keeps it in the current terminal"),
    ("olivercode watch [REPO] [--until-exit]", "Print one line per new stage row of the run log, such as `#169 in repo: validating`, and exit when a run ends or no drain holds the repo's run lock. With --until-exit, which needs REPO, print nothing while the drain runs and one line when it ends, with its landed and stopped counts and why. A session runs that form in the background. Reads only the run log, with no model or GitHub call"),
    ("olivercode rule add|check --repo PATH [FLAGS]", "Turn an owner rule into a check: add writes a rule (--id ID --text RULE --paths GLOB --forbid REGEX) to the repo's owner-rules.json, and check fails when a file under a rule's paths matches its forbid pattern"),
    ("olivercode decisions record|verify|show|import", "The decision ledger in ~/.olivercode/relays.jsonl: record --decision ID --thread ID [--words TEXT] --option A --option B --choice A [--by NAME] keeps the owner's exact words for one decision, verify ID proves a record is complete, show [ID] prints the records, and import FILE adopts a markdown decisions log as one record per ## heading or top-level bullet, the file left unchanged and a second run adding nothing. Entries older than 90 days, or citing a number that a later entry changed, are flagged for the owner to re-confirm"),
    ("olivercode owner add|list|done|summary", "Keep every step only the owner can take in ~/.olivercode/owner-queue.jsonl: add needs the session, the step and either the command tried with its error or --decision, then prints the Owner · title and pin steps, and done prints the steps that undo them. summary prints what is open and what changed in seven days, with no model call"),
    ("olivercode version-cut --story REF [--day YYYY-MM-DD] [--schedule | --unschedule]", "Cut a version in its own worktree: read every commit on main since the previous cut, pick MAJOR, MINOR or PATCH from docs/VERSIONING.md, set VERSION and write that version's CHANGELOG.md section grouped by story. Nothing new on main makes no version. --story names the story the cut files under, and --schedule runs it nightly at 23:50 through launchd"),
    ("olivercode docs-check", "Compare the launcher's command table, the gates table and the skills index against README.md and the docs, and fail on every miss with its fix"),
    ("olivercode health", "Run health checks on this machine: Claude Code hooks, skill links, voice copies, remotes and file sizes"),
    ("olivercode status [page [--fetch]] [--root DIR]", "`page` writes city.html to the OliverCode home from local files only, with no GitHub call. `page --fetch` reads the opened and closed counts and the check results from GitHub once, saves them with the time read, and writes the page. Without it, print this repo's open story count, the stories landed per day over the last seven days, the tokens per closed story from the run log and the date the count reaches zero at that pace, or that the date is not reachable when opens match or exceed closes. Reads GitHub REST only, with no model call"),
    ("olivercode update [--story REF]", "Pull this checkout's tracking branch fast-forward only, refusing a dirty, mid-rebase or diverged checkout with the one fix command, then re-run install and sync the private repos' hooks, committing them under the story with --story"),
    ("olivercode sync-hooks [--commit [--story REF]]", "Converge hooks + core.hooksPath in the private repos, and with --commit commit the changed hook files"),
    ("olivercode maintain [--fix | --schedule | --unschedule]", "Check this machine and repair what is safe: dangling links, dead worktrees, iCloud-evicted git files. --schedule runs it daily"),
    ("olivercode limits check [--root DIR]", "Print the tracked line count against the ceiling in docs/LIMITS.json. It warns when the count is over and exits 0 always"),
    ("olivercode handoff write PROJECT FILE | read PROJECT", "Keep one handoff per project in the current folder. write checks each `olivercode drain` and `dispatch` line in FILE parses without running it, files FILE as PROJECT-handoff-DATE.md and deletes the project's other handoffs, then prints the desktop-app calls that start the next thread, name it PROJECT 1 to 10 and move the pin to it. read prints the handoff and deletes it, with no archive copy, and gives the reading thread the same title and pin calls, which the thread write started makes only when its title or pin is missing. Other projects' files and folders are untouched"),
    ("olivercode wip save|list|restore REF [--to DIR]", "Snapshot uncommitted work (tracked and untracked) in this repo and its worktrees into refs/wip/ without touching the working tree, index or any branch. list shows the snapshots, restore checks one out into a new folder, and refs older than 7 days are pruned"),
    ("olivercode land WORKTREE STORY", "Land a story's worktree on main: rebase on origin/main, validate (twice at most), push HEAD:main (4 tries), then fast-forward a clean main checkout and delete the story's worktree, local branch and remote branch. Work that does not land stays in its worktree with no pushed branch. The log is ~/.olivercode/land/landN.log and ends RESULT pushed SHA"),
    ("olivercode promote", "Move the owner's staging branch to main: with no drain running, time one quick validation on main and one on staging and promote nothing when staging takes a quarter longer or more, else, once CI has passed on staging's head and main is an ancestor of staging, validate once, fast-forward main to staging's head so every story keeps its commit, and label each story it carries on-main. A failed validation leaves main, staging and every label as they were"),
    ("olivercode guide [NAME]","Print how work runs, the first steps, every command grouped by the job it does and every skill with the phrases that load it. With NAME, say what that command, gate, guard, scheduled job or skill does and where it lives"),
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


def usage_line(cmd: str) -> str:
    """The usage line of the command's row in COMMANDS, or the bare name when the table has no row for it."""
    for row, _ in COMMANDS:
        if row.split()[1:2] == [cmd]:
            return row
    return f"olivercode {cmd}"


def reject_extra(cmd: str, rest: list[str]) -> None:
    """Unknown arguments must fail loudly.

    Rejecting them beats ignoring them: `sync-hooks --root /somewhere` would otherwise
    sync the default repos and print a success message for work done on the wrong ones. The error is one line with
    the command's usage and the guide command, so a typo costs a line, not the whole table.
    """
    if rest:
        print(f"Error: unexpected argument(s) for '{cmd}': {' '.join(rest)}. Usage: {usage_line(cmd)}. "
              f"Guide: olivercode guide {cmd}")
        sys.exit(1)


def flags(argv: list[str], valued: set[str], plain: set[str] = frozenset()):
    """(values by flag, repeated --option list, positionals, plain flags seen), or None for an unknown or valueless flag."""
    vals: dict[str, str] = {}
    options: list[str] = []
    pos: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in valued:
            if i + 1 >= len(argv):
                return None
            if a == "--option":
                options.append(argv[i + 1])
            else:
                vals[a] = argv[i + 1]
            i += 2
        elif a in plain:
            seen.add(a)
            i += 1
        elif a.startswith("--"):
            return None
        else:
            pos.append(a)
            i += 1
    return vals, options, pos, seen
