"""Health checks on the machine's own environment: memory budget, commits behind, the clean-clone suite,
the state folder's size, the fleet repo, python3, gh, sleep settings and the launcher.

Split out of health_checks.py so each file reads in one sitting (#1125). `health_checks.py` re-exports
these names for `cmd_health.py`. Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lib import failure_log
from lib.cli import MIN_PYTHON, MIN_PYTHON_TEXT, PYTHON_FIX, gh_problem, python_version
from lib.limits import LIMITS_FILE
from lib.local_config import OC_ROOT, fleet_registry_path

MEMORY_WORDS = 5000


def _check_memory(oc_root: Path, budget: int = MEMORY_WORDS) -> tuple[int, int, int]:
    """The memory files stay within 5,000 words, and an entry that names a gone path is stale.

    Stale entries are listed and never deleted: the owner decides what to drop.
    """
    folder = oc_root / ".claude-optimization" / "memory"
    files = sorted(folder.glob("*.md")) if folder.is_dir() else []
    if not files:
        print("  [INFO] no memory files on this machine, so memory is not checked")
        return 0, 0, 0
    passed = failed = skipped = 0
    words = {f.name: len(f.read_text(encoding="utf-8").split()) for f in files}
    total = sum(words.values())
    if budget and total > budget:
        failed += 1
        largest = ", ".join(f"{n} ({w})" for n, w in sorted(words.items(), key=lambda x: -x[1])[:3])
        print(f"  [FAIL] memory holds {total} words, over the {budget} budget by {total - budget}. Largest: {largest}")
    else:
        passed += 1
        print(f"  [OK] memory holds {total} words" + f" of {budget}")
    stale = []
    for f in files:
        for ref in sorted(set(re.findall(r"`([~\w./-]+/[\w./-]+|[\w-]+\.(?:md|py|sh|json))`", f.read_text(encoding="utf-8")))):
            # A ~/ path names a home path whatever the base, so it is expanded before any join.
            candidates = [Path(ref).expanduser()] if ref.startswith("~") else [base / ref for base in (oc_root, Path.home())]
            if not any(c.exists() for c in candidates):
                stale.append(f"{f.name}: {ref}")
    if stale:
        skipped += 1
        print("  [WARN] stale memory entries name a path that is gone from here (nothing was deleted):")
        for line in stale[:10]:
            print(f"         {line}")
    else:
        passed += 1
        print("  [OK] no memory entry names a missing path")
    return passed, failed, skipped


def _check_commits_behind(oc_root: Path) -> tuple[int, int, int]:
    """Print how many commits this checkout is behind upstream/main (origin/main on a clone) and their one-line log.

    Reads only refs already fetched, so health stays offline. A checkout with neither remote ref has nothing to compare.
    """
    for ref in ("upstream/main", "origin/main"):
        done = subprocess.run(["git", "-C", str(oc_root), "log", "--oneline", f"HEAD..{ref}"], capture_output=True, text=True)
        if done.returncode == 0:
            break
    else:
        print("  [INFO] no upstream/main or origin/main fetched, so the commits behind were not counted")
        return 0, 0, 0
    lines = done.stdout.splitlines()
    if not lines:
        print(f"  [OK] level with {ref}")
        return 1, 0, 0
    print(f"  [WARN] {len(lines)} commit(s) behind {ref}. Run `olivercode update`. Newest first:")
    for line in lines[:15]:
        print(f"         {line}")
    return 0, 0, 1


SUITE_STALE_DAYS = 2


def suite_record_path() -> Path:
    """Where the daily job writes the clean-clone suite's record (maintain.check_suite)."""
    return failure_log.home() / "clean-clone-suite.json"


def _check_clean_clone_suite(record: Path | None = None, now: float | None = None) -> tuple[int, int, int]:
    """The clean-clone suite must have passed on a commit within two days (#977). A failed record names its failing modules, and a
    stale one means the daily job has not run. A machine with no record yet is skipped, since the job has not run there."""
    print("\nClean-clone suite:")
    path = record or suite_record_path()
    if not path.is_file():
        print("  [INFO] no clean-clone run recorded yet; the daily job runs it")
        return 0, 0, 1
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f"  [FAIL] {path} does not parse; run `olivercode maintain --fix` to rewrite it")
        return 0, 1, 0
    commit = data.get("commit") or "unknown"
    if data.get("exit"):
        print(f"  [FAIL] the clean-clone suite failed on commit {commit}: {', '.join(data.get('failed') or ['no module was named'])}")
        return 0, 1, 0
    age = ((time.time() if now is None else now) - data.get("at", 0)) / 86400
    if age > SUITE_STALE_DAYS:
        print(f"  [FAIL] the clean-clone suite last ran {age:.1f} days ago on commit {commit}; run `olivercode maintain --fix` or check the daily job")
        return 0, 1, 0
    print(f"  [OK] the clean-clone suite passed on commit {commit}: {data.get('tests', 0)} tests, {age:.1f} days ago")
    return 1, 0, 0


STATE_KEYS = ("stateEntries", "stateBytes", "stateLogBytes")
MIB = 1024 * 1024


def state_limits(root: Path | None = None) -> dict:
    """The state folder's ceilings in docs/LIMITS.json (#997). A key the file lacks reads as None, which switches its check off."""
    try:
        data = json.loads(((root or OC_ROOT) / LIMITS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {key: data.get(key) for key in STATE_KEYS}


def folder_bytes(home: Path) -> int:
    """The bytes under a folder, with links left out so a link to a large file elsewhere is not counted here."""
    total = 0
    for dirpath, _dirs, files in os.walk(home):
        for name in files:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                total += os.path.getsize(full)
    return total


def _check_state_folder(home: Path | None = None, limits: dict | None = None) -> tuple[int, int, int]:
    """The OliverCode home holds no more entries or bytes than docs/LIMITS.json allows (#997). Over a limit it fails and names the
    nightly job, `maintain --fix`, which clears the locks, dead output and oversized logs that grow the folder."""
    print("\nState folder:")
    home = home or failure_log.home()
    limits = state_limits() if limits is None else limits
    entries = len(list(home.iterdir())) if home.is_dir() else 0
    size = folder_bytes(home)
    text = f"{home} holds {entries} entries and {size / MIB:.1f} MB"
    over = []
    if limits["stateEntries"] is not None and entries > limits["stateEntries"]:
        over.append(f"{entries} entries against a limit of {limits['stateEntries']}")
    if limits["stateBytes"] is not None and size > limits["stateBytes"]:
        over.append(f"{size / MIB:.1f} MB against a limit of {limits['stateBytes'] / MIB:.1f} MB")
    if over:
        print(f"  [FAIL] {text}, over the limit in docs/LIMITS.json: {'; '.join(over)}. Run `olivercode maintain --fix` to clear what is not live")
        return 0, 1, 0
    print(f"  [OK] {text}, within the limit in docs/LIMITS.json")
    return 1, 0, 0


def _check_fleet_repo(dest: Path | None = None) -> tuple[int, int, int]:
    """The fleet folder holds the registry and owner rules, and it must be a git repo (#993). Health only reads: a loose folder fails
    and names the command that makes it a repo."""
    dest = dest or fleet_registry_path().parent
    print("\nFleet repo:")
    if not (dest / "repo-profiles.json").exists():
        print("  [INFO] no fleet folder here yet; `olivercode install` makes one")
        return 0, 0, 1
    if not (dest / ".git").exists():
        print(f"  [FAIL] {dest} is a loose folder, not a git repo; run `git -C {dest} init` and commit its files")
        return 0, 1, 0
    print(f"  [OK] {dest} is a git repo")
    return 1, 0, 0


def _check_python() -> tuple[int, int, int]:
    """The `python3` a shell finds must meet MIN_PYTHON (lib/cli.py).

    The hooks and gates run under that python3. An older one parses some of them and
    fails on others, so a half-working harness looks like a healthy one.
    """
    print("\nPython:")
    exe = shutil.which("python3")
    found = python_version(exe) if exe else None
    if found is None:
        print(f"  [FAIL] python3 not found or not runnable. Need Python {MIN_PYTHON_TEXT} or newer: {PYTHON_FIX}")
        return 0, 1, 0
    if found < MIN_PYTHON:
        print(f"  [FAIL] python3 is {found[0]}.{found[1]} ({exe}), and OliverCode needs {MIN_PYTHON_TEXT} or newer: {PYTHON_FIX}")
        return 0, 1, 0
    print(f"  [OK] python3 is {found[0]}.{found[1]}, at or above the minimum {MIN_PYTHON_TEXT}")
    return 1, 0, 0


def _gh_auth_status() -> subprocess.CompletedProcess:
    return subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=30)


def _check_gh_version(problem=gh_problem) -> tuple[int, int, int]:
    """The `gh` a shell finds must meet MIN_GH, because four commands page the REST API with `--paginate --slurp`."""
    print("\nGitHub CLI version:")
    old = problem()
    if old:
        print(f"  [FAIL] {old}")
        return 0, 1, 0
    print("  [OK] gh is new enough, or not installed (its own check reports that)")
    return 1, 0, 0


def _check_gh_auth(runner=None) -> tuple[int, int, int]:
    """`gh` must be signed in, because the backlog skill and the board checks all run through it.

    Health must exit 0 on a clone with no local context (docs/SETUP.md), so a missing gh and a signed-out gh
    are both warnings. The signed-out row names the fix. `runner` stands in for
    `gh auth status` in tests, so no check here makes a live call.
    """
    print("\nGitHub CLI:")
    try:
        result = (runner or _gh_auth_status)()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  [WARN] gh is not installed or did not answer, so its sign-in was not checked. Install it from https://cli.github.com")
        return 0, 0, 1
    if result.returncode == 0:
        if "project" not in _scopes(result):
            print("  [FAIL] gh is signed in without the project scope, so no board can take a story. Run: gh auth refresh -s project")
            return 0, 1, 0
        print("  [OK] gh is signed in with the repo and project scopes")
        return 1, 0, 0
    print("  [WARN] gh is signed out, so the backlog and board checks cannot reach GitHub. Run: gh auth login")
    return 0, 0, 1


def _scopes(result) -> set[str]:
    """The token scopes `gh auth status` lists. It reads the token's own record, so no GraphQL point is spent (#994)."""
    text = f"{result.stdout or ''}{result.stderr or ''}"
    found = re.search(r"Token scopes:\s*(.+)", text)
    return set(re.findall(r"'([^']+)'", found.group(1))) if found else set()


def gh_ready() -> str:
    """"" when gh is installed, signed in and holds the project scope, else the one line that names the fix (#994)."""
    try:
        result = _gh_auth_status()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "gh is not installed or did not answer. Install it from https://cli.github.com, then run: gh auth login"
    if result.returncode:
        return "gh is not signed in. Run: gh auth login, then gh auth refresh -s project"
    if "project" not in _scopes(result):
        return "gh is signed in without the project scope. Run: gh auth refresh -s project"
    return ""


SLEEP_FIX = ("In System Settings, open Battery or Energy and turn off sleep on power adapter and display sleep (Never), "
             "or run `caffeinate -dimsu` in a terminal before leaving")


def sleep_warning(pmset_text: str) -> str | None:
    """The one plain line naming the fix when `pmset -g` shows a sleep that would stop a session, else None.

    Display sleep and system sleep both count when their timer is above 0 minutes. A system sleep that
    powerd reports as prevented by caffeinate holds the machine awake, so it does not count.
    """
    stops = []
    for line in pmset_text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] not in ("sleep", "displaysleep") or not parts[1].isdigit() or int(parts[1]) == 0:
            continue
        if parts[0] == "sleep" and "caffeinate" in line:
            continue
        stops.append("display sleep" if parts[0] == "displaysleep" else "system sleep")
    if not stops:
        return None
    return f"This Mac would stop work on {' and '.join(stops)}. {SLEEP_FIX}"


def _pmset_text() -> str:
    return subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=15).stdout


def _check_sleep(runner=None, system: str | None = None) -> tuple[int, int, int]:
    """Warn, never fail, when a sleep setting would stop a session. Skips on a host that is not macOS.

    `runner` stands in for `pmset -g` in tests, so no check here reads the live machine.
    """
    print("\nSleep settings:")
    if (system or sys.platform) != "darwin":
        print("  [INFO] not macOS, so sleep settings were not checked")
        return 0, 0, 0
    try:
        text = (runner or _pmset_text)()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  [WARN] pmset did not answer, so sleep settings were not checked")
        return 0, 0, 1
    warning = sleep_warning(text)
    if warning:
        print(f"  [WARN] {warning}")
        return 0, 0, 1
    print("  [OK] no sleep setting would stop work")
    return 1, 0, 0


def _check_launcher(oc_root: Path, launcher: Path | None = None) -> tuple[int, int, int]:
    """A launcher at ~/.local/bin/olivercode, where install puts it (or the path in OLIVERCODE_LAUNCHER), must reach a launcher that exists.

    After the checkout moves, the link or wrapper keeps pointing at the old folder and every
    `olivercode` call dies with a bare "No such file". No launcher there is a skip.
    """
    from lib.queue_shim import launcher_path
    launcher = launcher or Path(os.environ.get("OLIVERCODE_LAUNCHER") or launcher_path())
    print("\nLauncher:")
    repair = f"ln -sf {oc_root / 'scripts' / 'olivercode'} {launcher}"
    if not launcher.is_symlink() and not launcher.exists():
        print(f"  [INFO] no launcher at {launcher} — not checked")
        return 0, 0, 0
    if launcher.is_symlink():
        target = os.readlink(launcher)
        if launcher.exists():
            print(f"  [OK] {launcher} reaches {launcher.resolve()}")
            return 1, 0, 0
        print(f"  [FAIL] {launcher} points at {target}, which does not exist. Repair it with: {repair}")
        return 0, 1, 0
    text = launcher.read_text(errors="ignore")
    dead = [p for p in re.findall(r"\"(/[^\"$]+)\"|'(/[^'$]+)'|(?:=|exec \S+ )(/[^\s\"'$]+)", text)
            for p in p if p and not Path(p).exists()]
    if dead:
        print(f"  [FAIL] {launcher} names {dead[0]}, which does not exist. Repair it with: {repair}")
        return 0, 1, 0
    print(f"  [OK] {launcher} reaches an existing launcher")
    return 1, 0, 0
