"""`olivercode maintain`: check this machine's harness and repair what is safe to repair.

Each step returns the problems it found and, with --fix, repairs the ones that cannot lose work: it re-points
a dangling activation link, prunes a worktree whose folder is gone, downloads git files that iCloud evicted
from disk, moves .git out of a synced folder, and clears numbered sync-conflict copies (hygiene.py). A problem that is not safe to change on its own (hooks
that drifted, a checkout outside repoRoot, a doc that trails its code, a failing health check) is reported, written to the failure log, and left alone.
`--schedule` installs a daily launchd job that runs `maintain --fix`.
"""

from __future__ import annotations

import contextlib
import io
import os
import plistlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, hygiene, placement
from lib.local_config import OC_ROOT, claude_dir

LABEL = "com.olivercode.maintain"
DOWNLOAD_SECONDS = 60


@dataclass
class Problem:
    step: str
    text: str
    fixable: bool = False
    fixed: bool = False


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)


def _repos(cfg: placement.Config) -> list[Path]:
    if not cfg.root.is_dir():
        return []
    return [p for p in sorted(cfg.root.iterdir())
            if not p.name.startswith("_") and ((p / ".git").is_dir() or (p / hygiene.NOSYNC).is_dir())]


def dataless_files(repo: Path) -> list[Path]:
    """Files in the repo's .git that iCloud evicted: they read as empty until downloaded, and git hangs on them."""
    ran = subprocess.run(["find", str((repo / ".git").resolve()), "-type", "f", "-flags", "+dataless"], capture_output=True, text=True)
    return [Path(line) for line in ran.stdout.splitlines() if line]


def _read(path: Path, seconds: int) -> bool:
    try:
        subprocess.run(["cat", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds)
        return True
    except subprocess.TimeoutExpired:
        return False


def download(paths: list[Path], seconds: int = DOWNLOAD_SECONDS) -> int:
    """Read each file once so macOS downloads it, eight at a time. Returns how many were read."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return sum(pool.map(lambda p: _read(p, seconds), paths))


def check_links(fix: bool, install=None) -> list[Problem]:
    """A dangling CLAUDE.md, VOICE.md or skill link loads no rules. `install` re-points them."""
    broken = [p for p in [claude_dir() / "CLAUDE.md", claude_dir() / "VOICE.md", *sorted((claude_dir() / "skills").glob("*"))]
              if p.is_symlink() and not p.exists()]
    if not broken:
        return []
    problem = Problem("links", f"{len(broken)} dangling link(s) in ~/.claude: " + ", ".join(p.name for p in broken[:5]), fixable=True)
    if fix:
        if install is None:
            from lib.cmd_install import command_install
            install = lambda: command_install(OC_ROOT)  # noqa: E731
        with contextlib.redirect_stdout(io.StringIO()):
            install()
        problem.fixed = not any(p.is_symlink() and not p.exists() for p in broken)
    return [problem]


def check_worktrees(cfg: placement.Config, fix: bool) -> list[Problem]:
    """A worktree whose folder is gone leaves metadata that git keeps listing. `git worktree prune` drops only that."""
    found = []
    for repo in _repos(cfg):
        listing = _git(repo, "worktree", "list", "--porcelain").stdout
        gone = [l[9:] for l in listing.splitlines() if l.startswith("worktree ") and not Path(l[9:]).exists()]
        if not gone:
            continue
        problem = Problem("worktrees", f"{repo.name}: {len(gone)} worktree(s) with no folder: {', '.join(gone[:3])}", fixable=True)
        if fix:
            _git(repo, "worktree", "prune")
            after = _git(repo, "worktree", "list", "--porcelain").stdout
            problem.fixed = not any(not Path(l[9:]).exists() for l in after.splitlines() if l.startswith("worktree "))
        found.append(problem)
    return found


def check_icloud(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Evicted .git files make git hang. Reading them downloads them."""
    found = []
    for repo in _repos(cfg):
        files = dataless_files(repo)
        if not files:
            continue
        problem = Problem("icloud", f"{repo.name}: {len(files)} git file(s) evicted by iCloud", fixable=True)
        if fix:
            download(files)
            problem.fixed = not dataless_files(repo)
        found.append(problem)
    return found


def check_placement(cfg: placement.Config) -> list[Problem]:
    """A checkout outside repoRoot is the owner's to move, so it is reported with the command that moves it."""
    return [Problem("placement", f"{f.kind} out of place: {f.path}. {f.fix}") for f in placement.findings(cfg)]


def check_copies(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Numbered sync-conflict copies: identical ones are deleted, older ones archived, newer ones left for the owner."""
    found = []
    for repo in _repos(cfg):
        copies = hygiene.stray_copies(repo, fetch=hygiene.download if fix else None)
        if not copies:
            continue
        keep = [c for c in copies if c.verdict == "newer"]
        problem = Problem("copies", f"{repo.name}: {len(copies)} numbered sync copy(ies), {len(keep)} newer than the original", fixable=not keep)
        if fix:
            hygiene.clear_copies(repo, cfg.archive, copies)
            problem.fixed = not keep and not hygiene.stray_copies(repo)
            problem.fixable = True
        found.append(problem)
    return found


def check_git_sync(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Under a synced repoRoot, a plain .git folder can be evicted, duplicated or half-synced. Moving it out of the sync is safe."""
    marker = hygiene.synced_marker(cfg.root)
    found = []
    for repo in _repos(cfg) if marker else []:
        if hygiene.git_protected(repo):
            continue
        problem = Problem("gitsync", f"{repo.name}: .git is inside {marker}", fixable=True)
        if fix:
            why = hygiene.protect_git(repo, cfg.archive)
            problem.fixed = not why
            problem.text += f" ({why})" if why else ""
        found.append(problem)
    return found


def check_docs(cfg: placement.Config) -> list[Problem]:
    """A document that trails the code it names is advisory: only the owner knows which side is right."""
    return [Problem("docs", f"{repo.name}: {line}") for repo in _repos(cfg) for line in hygiene.stale_docs(repo)]


def check_health() -> list[Problem]:
    """Anything `olivercode health` fails on that the steps above did not repair."""
    from lib.cmd_health import command_health
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = command_health(None)
    lines = [l.strip()[7:] for l in out.getvalue().splitlines() if l.strip().startswith("[FAIL]")]
    return [Problem("health", l) for l in lines] if code else []


def run(fix: bool, cfg: placement.Config | None = None, health: bool = True) -> list[Problem]:
    cfg = cfg or placement.config()
    problems = [*check_links(fix), *check_worktrees(cfg, fix), *check_icloud(cfg, fix), *check_copies(cfg, fix),
                *check_git_sync(cfg, fix), *check_placement(cfg), *check_docs(cfg)]
    if health:
        problems += check_health()
    return problems


def report(problems: list[Problem], fix: bool) -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"OliverCode maintain {stamp} ({'fixing' if fix else 'checking only'})"]
    left = 0
    for p in problems:
        if p.fixed:
            state = "FIXED"
        elif p.fixable and not fix:
            state = "FIXABLE (run with --fix)"
        else:
            state = "NEEDS A DECISION" if not p.fixable else "NOT FIXED"
        lines.append(f"  [{state}] {p.step}: {p.text}")
        if not p.fixed:
            left += 1
            failure_log.record("maintain", f"{p.step}: {p.text}", "machine")
    if not problems:
        lines.append("  [OK] nothing to repair")
    text = "\n".join(lines)
    print(text)
    log = failure_log.home() / "maintenance.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return 1 if left else 0


def plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(OC_ROOT / "scripts" / "olivercode"), "maintain", "--fix"],
        "StartCalendarInterval": {"Hour": 6, "Minute": 30},
        "StandardOutPath": str(failure_log.home() / "maintain.out"),
        "StandardErrorPath": str(failure_log.home() / "maintain.out"),
    }


def _agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def schedule(on: bool) -> int:
    domain = f"gui/{os.getuid()}"
    path = _agent_path()
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    if not on:
        path.unlink(missing_ok=True)
        print(f"Removed the daily maintenance job ({LABEL}).")
        return 0
    failure_log.home().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(plist()))
    ran = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if ran.returncode:
        print(f"Wrote {path} but launchctl refused it: {ran.stderr.strip()}")
        return 1
    print(f"Installed {LABEL}: `olivercode maintain --fix` runs daily at 06:30. Remove it with `olivercode maintain --unschedule`.")
    return 0


def command_maintain(argv: list[str]) -> int:
    if argv == ["--schedule"]:
        return schedule(True)
    if argv == ["--unschedule"]:
        return schedule(False)
    if argv not in ([], ["--fix"]):
        print("Usage: olivercode maintain [--fix | --schedule | --unschedule]")
        return 1
    fix = argv == ["--fix"]
    return report(run(fix), fix)
