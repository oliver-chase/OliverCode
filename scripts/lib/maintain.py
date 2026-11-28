"""`olivercode maintain`: check this machine's harness and repair what is safe to repair.

Each step returns the problems it found and, with --fix, repairs the ones that cannot lose work: it re-points
a dangling activation link, prunes a worktree whose folder is gone, deletes merged local branches, downloads git files that iCloud evicted
from disk, moves .git out of a synced folder, and clears numbered sync-conflict copies (hygiene.py). It also keeps the OliverCode home to what is live: a lock no process holds, the output of a removed job and a log over its size limit are removed or cut. A problem that is not safe to change on its own (hooks
that drifted, a repo inside a synced folder, a checkout outside repoRoot, a doc that trails its code, a failing health check) is reported, written to the failure log, and left alone.
With --fix the daily run also tests a fresh clone of OliverCode's HEAD with scripts/run-tests.sh and records the commit, exit code and test count for `olivercode health`.
`--schedule` installs a daily launchd job that runs `maintain --fix`, and `olivercode install` loads it too.
"""

from __future__ import annotations

import contextlib
import fcntl
import getpass
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib.cli import MIN_PYTHON, newer_python
from lib import failure_log, hygiene, intake, launchd, placement, repo_gates, repo_state
from lib import local_config
from lib.local_config import OC_ROOT, claude_dir
from lib import gitfiles

LABEL = "com.olivercode.maintain"
DOWNLOAD_SECONDS = 60


@dataclass
class Problem:
    step: str
    text: str
    fixable: bool = False
    fixed: bool = False


def _repos(cfg: placement.Config) -> list[Path]:
    if not cfg.root.is_dir():
        return []
    return [p for p in sorted(cfg.root.iterdir())
            if not p.name.startswith("_") and ((p / ".git").is_dir() or (p / hygiene.NOSYNC).is_dir())
            and not repo_state.skipped(p.name, p)]


def dataless_files(repo: Path) -> list[Path]:
    """Files in the repo's .git that iCloud evicted: they read as empty until downloaded, and git hangs on them."""
    ran = subprocess.run(["find", str((repo / ".git").resolve()), "-type", "f", "-flags", "+dataless"], capture_output=True, text=True)
    return [Path(line) for line in ran.stdout.splitlines() if line]


def check_links(fix: bool, install=None) -> list[Problem]:
    """A dangling CLAUDE.md, VOICE.md or skill link loads no rules. `install` re-points them."""
    names = ("CLAUDE.md", "VOICE.md", "DESIGN.md")
    broken = [p for p in [*(claude_dir() / n for n in names), *sorted((claude_dir() / "skills").glob("*"))] if p.is_symlink() and not p.exists()]
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
        gone = [l[9:] for l in gitfiles.run(repo, "worktree", "list", "--porcelain", timeout=60).stdout.splitlines() if l.startswith("worktree ") and not Path(l[9:]).exists()]
        if not gone:
            continue
        problem = Problem("worktrees", f"{repo.name}: {len(gone)} worktree(s) with no folder: {', '.join(gone[:3])}", fixable=True)
        if fix:
            gitfiles.run(repo, "worktree", "prune", timeout=60)
            after = gitfiles.run(repo, "worktree", "list", "--porcelain", timeout=60).stdout
            problem.fixed = not any(not Path(l[9:]).exists() for l in after.splitlines() if l.startswith("worktree "))
        found.append(problem)
    return found


STALE_BRANCH_HOURS = 24
PROTECTED_BRANCHES = {"main", "master", "develop"}


def _base_ref(repo: Path) -> str | None:
    """The ref branches are merged into: origin's main or master, else the local one."""
    for ref in ("origin/main", "origin/master", "main", "master"):
        if gitfiles.run(repo, "rev-parse", "--verify", "--quiet", ref, timeout=60).returncode == 0:
            return ref
    return None


def _checked_out(repo: Path) -> set[str]:
    """Branches a worktree of the repo has checked out. The worktree's session may be live, so these are never touched."""
    return {l[len("branch refs/heads/"):] for l in gitfiles.run(repo, "worktree", "list", "--porcelain", timeout=60).stdout.splitlines() if l.startswith("branch refs/heads/")}


def check_branches(cfg: placement.Config, fix: bool, now: float | None = None) -> list[Problem]:
    """Merged local branches are clutter, and with --fix only those are deleted (`git branch -d` refuses an unmerged one).
    An unmerged branch older than 24 hours that no worktree has checked out has no live session, so it is reported and left."""
    now = __import__("time").time() if now is None else now
    found = []
    for repo in _repos(cfg):
        if (base := _base_ref(repo)) is None:
            continue
        busy = _checked_out(repo) | PROTECTED_BRANCHES
        merged = set(gitfiles.run(repo, "branch", "--merged", base, "--format=%(refname:short)", timeout=60).stdout.split())
        mergeable = sorted(merged - busy)
        remote = sorted(b for b in gitfiles.run(repo, "branch", "-r", "--merged", base, "--format=%(refname:short)", timeout=60).stdout.split()
                        if "/HEAD" not in b and b.split("/", 1)[-1] not in PROTECTED_BRANCHES and b != "origin")
        if mergeable or remote:
            text = f"{repo.name}: {len(mergeable)} merged local branch(es)" + (f" ({', '.join(mergeable[:4])})" if mergeable else "")
            text += f" and {len(remote)} merged remote branch(es) on origin, deleted only when deleteMergedRemoteBranches is true in olivercode.local.json" if remote else ""
            problem = Problem("branches", text, fixable=bool(mergeable))
            if fix and mergeable:
                for name in mergeable:
                    gitfiles.run(repo, "branch", "-d", name, timeout=60)
                after = set(gitfiles.run(repo, "branch", "--format=%(refname:short)", timeout=60).stdout.split())
                problem.fixed = not (set(mergeable) & after)
            found.append(problem)
        stale = []
        for line in gitfiles.run(repo, "for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads", timeout=60).stdout.splitlines():
            name, _, stamp = line.rpartition(" ")
            if name not in merged and name not in busy and stamp.isdigit() and now - int(stamp) > STALE_BRANCH_HOURS * 3600:
                stale.append(name)
        if stale:
            found.append(Problem("branches", f"{repo.name}: {len(stale)} unmerged branch(es) older than {STALE_BRANCH_HOURS} hours with no worktree: {', '.join(sorted(stale)[:4])}"))
    return found


def check_icloud(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Evicted .git files make git hang. Reading them downloads them."""
    found = []
    for repo in _repos(cfg):
        if not (files := dataless_files(repo)):
            continue
        found.append(problem := Problem("icloud", f"{repo.name}: {len(files)} git file(s) evicted by iCloud", fixable=True))
        if fix:
            hygiene.download(files, DOWNLOAD_SECONDS)
            problem.fixed = not dataless_files(repo)
    return found


def check_hooks_path(cfg: placement.Config, fix: bool) -> list[Problem]:
    """An absolute core.hooksPath in a repo that ships .githooks breaks worktree commits, and resetting it to `.githooks` loses nothing."""
    found = []
    for repo in _repos(cfg):
        if not (configured := repo_gates.hooks_path(repo)) or not Path(configured).expanduser().is_absolute() or not repo_gates.has_gates(repo):
            continue
        found.append(problem := Problem("hookspath", f"{repo.name}: core.hooksPath is the absolute path {configured}", fixable=True))
        if fix:
            gitfiles.run(repo, "config", "core.hooksPath", ".githooks", timeout=60)
            problem.fixed = repo_gates.hooks_path(repo) == ".githooks"
    return found


def check_worktree_hooks(cfg: placement.Config) -> list[Problem]:
    """Each linked worktree whose commit hooks predate origin/main, named once. Left alone: a rebase is the owner's call."""
    from lib.health_checks import stale_hook_text, stale_worktree_hooks
    return [Problem("hooks", stale_hook_text(path, why)) for path, why in stale_worktree_hooks(placement.worktrees(cfg))]


def check_placement(cfg: placement.Config) -> list[Problem]:
    """A checkout outside repoRoot is the owner's to move, so it is reported with the command that moves it."""
    return [Problem("placement", f"{f.kind} out of place: {f.path}. {f.fix}") for f in placement.findings(cfg)]


def check_copies(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Numbered sync-conflict copies: identical ones are deleted, older ones archived, newer ones left for the owner."""
    found = []
    for repo in _repos(cfg):
        if not (copies := hygiene.stray_copies(repo, fetch=hygiene.download if fix else None)):
            continue
        keep = [c for c in copies if c.verdict == "newer"]
        found.append(problem := Problem("copies", f"{repo.name}: {len(copies)} numbered sync copy(ies), {len(keep)} newer than the original", fixable=not keep))
        if fix:
            hygiene.clear_copies(repo, cfg.archive, copies)
            problem.fixed = not keep and not hygiene.stray_copies(repo)
    return found


def check_git_sync(cfg: placement.Config, fix: bool) -> list[Problem]:
    """Under a synced repoRoot, a plain .git folder can be evicted, duplicated or half-synced. Moving it out of the sync is safe."""
    found, marker = [], placement.synced_place(cfg.root)
    for repo in _repos(cfg) if marker else []:
        if hygiene.git_protected(repo):
            continue
        found.append(problem := Problem("gitsync", f"{repo.name}: .git is inside {marker}", fixable=True))
        if fix:
            problem.fixed = not (why := hygiene.protect_git(repo, cfg.archive))
            problem.text += f" ({why})" if why else ""
    return found


def check_synced(cfg: placement.Config, fleet: list[Path] | None = None, home: Path | None = None) -> list[Problem]:
    """A repo inside a synced folder loses working files whenever the sync service evicts them, so it is reported with the move."""
    if fleet is None:
        from lib.local_config import private_repos
        fleet = list(private_repos().values())
    found = []
    place = placement.synced_place(cfg.root, home)
    if place:
        found.append(Problem("synced", f"repoRoot {cfg.root} is inside {place}, which can evict its files. "
                                       f"Clone each repo into a folder outside synced places (for example {placement.SAFE_ROOT}), copy over its untracked files and set repoRoot to it"))
    for repo in fleet:
        if place and placement.inside(repo, cfg.root):
            continue
        where = placement.synced_place(repo, home) if repo.exists() else ""
        if where:
            found.append(Problem("synced", f"{repo.name}: {repo} is inside {where}, which can evict its files. "
                                           f"Clone it into a folder outside synced places (for example {placement.SAFE_ROOT}/{repo.name}) and copy over its untracked files"))
    return found


def check_docs(cfg: placement.Config) -> list[Problem]:
    """A document that trails the code it names is advisory: only the owner knows which side is right."""
    return [Problem("docs", f"{repo.name}: {line}") for repo in _repos(cfg) for line in hygiene.stale_docs(repo)]


def main_checkout_lag(root: Path, fetch: bool = False, branch: str = "main") -> tuple[int, str]:
    """(commits the checkout trails origin/main by, its state): 'clean' when it is on main with no edits and no local commits, so
    a fast-forward is safe, else 'edited', 'diverged' or 'off main'. Fetches first when asked."""
    if fetch:
        gitfiles.run(root, "fetch", "-q", "origin", timeout=60)
    behind = gitfiles.run(root, "rev-list", "--count", f"HEAD..origin/{branch}", timeout=60)
    if behind.returncode:
        return 0, "unknown"
    if gitfiles.run(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=60).stdout.strip() != branch:
        state = "off main"
    elif gitfiles.run(root, "status", "--porcelain", "--untracked-files=no", timeout=60).stdout.strip():
        state = "edited"
    elif gitfiles.run(root, "rev-list", "--count", f"origin/{branch}..HEAD", timeout=60).stdout.strip() != "0":
        state = "diverged"
    else:
        state = "clean"
    return int(behind.stdout.strip() or 0), state


def fast_forward(root: Path, fetch: bool = False, branch: str = "main") -> tuple[int, str, bool]:
    """Fast-forward the checkout to origin/main when it is clean. Returns (commits behind before, state, whether it moved);
    an edited, diverged or off-main checkout is left alone."""
    behind, state = main_checkout_lag(root, fetch=fetch, branch=branch)
    moved = bool(behind) and state == "clean" and gitfiles.run(root, "merge", "-q", "--ff-only", f"origin/{branch}", timeout=60).returncode == 0
    return behind, state, moved


def check_main_checkout(fix: bool, root: Path | None = None) -> list[Problem]:
    """The OliverCode checkout that runs the hooks fast-forwards to origin/main when it is clean, and reports its lag when it has
    local edits or its own commits, because the hooks and gates it runs are then older than main's."""
    root = root or OC_ROOT
    fetched = gitfiles.run(root, "fetch", "-q", "origin", timeout=60)
    failed = [Problem("checkout", f"{root}: git fetch failed: {fetched.stderr.strip()[:200]}", fixable=True)] if fetched.returncode else []
    behind, state = main_checkout_lag(root)
    from lib import main_checkout
    drifted = failed + [Problem("checkout", line) for line in main_checkout.drift(root)]
    if not behind:
        return drifted
    problem = Problem("checkout", f"{root} is {behind} commit(s) behind origin/main and {state}" + ("" if state == "clean" else ", so it was not updated"),
                      fixable=state == "clean")
    if fix:
        problem.fixed = fast_forward(root)[2]
    return [problem, *drifted]


def check_health() -> list[Problem]:
    """Anything `olivercode health` fails on that the steps above did not repair."""
    from lib.cmd_health import command_health
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = command_health()
    lines = [l.strip()[7:] for l in out.getvalue().splitlines() if l.strip().startswith("[FAIL]")]
    return [Problem("health", l) for l in lines] if code else []


STRAY_COMMANDS = {"claude", "ffmpeg", "python", "python3", "Python"}
ONE_TIME_DATE = re.compile(r"-(\d{4}-\d{2}-\d{2})$")


def _stray_processes(ps_text: str, own_pid: int, user: str | None = None) -> list[str]:
    """One line per claude, ffmpeg or python process of this user that has run for a day or more, from `ps -axo pid=,etime=,user=,comm=` text.
    Another account's processes are not this user's to report."""
    user = user or getpass.getuser()
    out = []
    for line in ps_text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or "-" not in parts[1] or parts[0] == str(own_pid) or parts[2] != user:
            continue
        if Path(parts[3]).name in STRAY_COMMANDS:
            out.append(f"process {parts[0]} ({Path(parts[3]).name}) owned by {parts[2]} has run {parts[1].split('-')[0]} day(s)")
    return out


def check_tidy(cfg: placement.Config, fix: bool, ps_text: str | None = None, tasks_dir: Path | None = None, today: str | None = None) -> list[Problem]:
    """The daily tidy: with --fix, remove merged and clean worktrees (the `olivercode clean --apply` step). List, and delete none of, the
    worktrees that stay and why, branches with commits not on the default branch, claude, ffmpeg and python processes older than a day,
    and one-time scheduled tasks whose dated name has passed."""
    found: list[Problem] = []
    removed, kept = [], []
    trees = placement.worktrees(cfg)
    if fix:
        lines = placement.clean(cfg, apply=True, remote=local_config.delete_merged_remote_branches())  # deleting on origin is the owner's call
        removed = [l for l in lines if l.startswith("REMOVE")]
        found += [Problem("tidy", l, fixable=True) for l in lines if l.startswith("FAILED")]
    gone = {l.split(" ", 1)[1] for l in removed}
    for wt in trees:
        if str(wt.path) in gone:
            continue
        why = "uncommitted changes" if wt.dirty else placement.held_reason(wt) if wt.merged else f"commits not on the default branch ({wt.branch or 'detached'})"
        if why:
            age = gitfiles.run(wt.path, "log", "-1", "--format=%cr", timeout=60).stdout.strip() or "no commits"
            kept.append(f"{wt.path} ({why}; last commit {age})")
    if removed:
        found.append(Problem("tidy", f"removed {len(removed)} merged and clean worktree(s)", fixable=True, fixed=True))
    if kept:
        found.append(Problem("tidy", f"{len(kept)} worktree(s) stay for the owner's decision:\n    " + "\n    ".join(kept)))
    if ps_text is None:
        ps_text = subprocess.run(["ps", "-axo", "pid=,etime=,user=,comm="], capture_output=True, text=True, timeout=20).stdout
    stray = _stray_processes(ps_text, os.getpid())
    if stray:
        found.append(Problem("tidy", f"{len(stray)} long-running process(es), none stopped:\n    " + "\n    ".join(stray)))
    today = today or datetime.now().strftime("%Y-%m-%d")
    tasks_dir = tasks_dir or claude_dir() / "scheduled-tasks"
    spent = [p.parent.name for p in sorted(tasks_dir.glob("*/SKILL.md")) if (m := ONE_TIME_DATE.search(p.parent.name)) and m.group(1) < today] if tasks_dir.is_dir() else []
    if spent:
        found.append(Problem("tidy", f"{len(spent)} one-time scheduled task(s) are past their date, none deleted: {', '.join(spent)}"))
    return found


def check_retired_jobs(fix: bool, agents: Path | None = None) -> list[Problem]:
    """A launchd job whose command no longer exists fails every run, and removing its plist loses nothing."""
    from lib.cmd_install import REMOVED_JOBS
    agents = agents or launchd.agents_dir()
    found = []
    for label in REMOVED_JOBS:
        plist = agents / f"{label}.plist"
        if not plist.exists():
            continue
        problem = Problem("retiredjob", f"{label} is still installed and its command is gone", fixable=True)
        if fix:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
            plist.unlink(missing_ok=True)
            problem.fixed = not plist.exists()
        found.append(problem)
    return found


def check_job_python(agents: Path | None = None) -> list[Problem]:
    """The installed daily job must run a python3 at the minimum; the plist names the one it runs."""
    plist_file = (agents or launchd.agents_dir()) / f"{LABEL}.plist"
    args = launchd.job_arguments(plist_file)
    if not args:
        return []
    exe = args[0]
    from lib.cli import python_version
    found = python_version(exe)
    if found is not None and found >= MIN_PYTHON:
        return []
    return [Problem("jobpython", f"the daily job runs {exe} ({'.'.join(map(str, found)) if found else 'unknown version'}), below {'.'.join(map(str, MIN_PYTHON))}: run `olivercode maintain --schedule` to reinstall it with {job_python()}")]


def check_queues(fix: bool) -> list[Problem]:
    """Closes each denied-step owner line whose check now passes, once `maintain --fix` runs. It creates no issue."""
    if not fix:
        return []
    from lib import denials
    try:
        denials.close_resolved()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return [Problem("queues", f"the owner queue was not processed: {error}", fixable=False)]
    return []


def check_outsiders(fix: bool) -> list[Problem]:
    """Queues each issue or pull request by an author outside `allowedAuthors` for the owner once."""
    from lib import cmd_sweep, outsiders
    try:
        cfgs = [json.loads(p.read_text()) for _, p in cmd_sweep.boards()] if fix else []
        outsiders.check([(c["repoName"], f"{c['repoOwner']}/{c['repoName']}") for c in cfgs])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return [Problem("outsiders", f"the outsider check did not run: {error}", fixable=False)]
    return []


def suite_record(code: int, out: str) -> dict:
    """The record of one clean-clone run: the commit it tested, its exit code, its test count and the modules that failed.
    The count is the summary line smoke_runner prints last, since a failed module's own `Ran` line comes first."""
    commit = re.search(r"on commit (\w+)", out)
    ran = re.findall(r"Ran (\d+) tests across", out)
    return {"commit": commit.group(1) if commit else "", "exit": code, "tests": int(ran[-1]) if ran else 0,
            "failed": re.findall(r"^--- (.+) ---$", out, re.M), "at": datetime.now(timezone.utc).timestamp()}


def run_clean_clone_suite(root: Path) -> dict:
    """Runs scripts/run-tests.sh on root, which tests a fresh clone of its HEAD, so uncommitted edits and this machine's branch names cannot pass it."""
    done = subprocess.run(["bash", str(root / "scripts" / "run-tests.sh"), str(root)], capture_output=True, text=True)
    return suite_record(done.returncode, done.stdout + done.stderr)


def check_suite(fix: bool, root: Path | None = None, record: Path | None = None) -> list[Problem]:
    """The daily job runs the clean-clone suite once and writes its record for `olivercode health`. A failing run is a problem that names its modules."""
    if not fix:
        return []
    from lib.health_checks import suite_record_path
    result = run_clean_clone_suite(root or OC_ROOT)
    record = record or suite_record_path()
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(result))
    if not result["exit"]:
        return []
    return [Problem("suite", f"the clean-clone suite failed on commit {result['commit'] or 'unknown'}: {', '.join(result['failed']) or 'no module was named'}")]


def failure_gaps() -> list[tuple[str, str, str]]:
    """(repo, title, body) for each failing check the nightly run can name a repo for: a worktree whose commit hooks predate
    origin/main is filed under its own origin."""
    from lib import placement
    from lib.health_checks import stale_hook
    gaps = []
    for wt in placement.worktrees():
        path = Path(wt.path)
        why = stale_hook(path)
        slug = (repo_state.origin(path, timeout=60) or "") if why else ""
        if slug:
            gaps.append((slug, f"Rebase {path.name} onto origin/main to refresh its commit hooks",
                         f"The nightly maintenance job finds the commit hooks in {path} older than origin/main ({why}).\n\n"
                         f"Fix: `git -C \"{path}\" rebase origin/main`, then `olivercode worktree fix \"{path}\"`.\n"))
    return gaps


def check_failure_gaps(fix: bool) -> list[Problem]:
    """The daily run reports each failing check as a problem that names its repo and fix. It files no story and writes no list.
    A gate blocked 3 or more times is reported with its reason and latest time. A check that cannot read its inputs is reported."""
    if not fix:
        return []
    try:
        gaps = failure_gaps()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return [Problem("gaps", f"the failing checks could not be read: {error}", fixable=False)]
    return [Problem("gaps", f"{repo}: {title}. {body.strip().splitlines()[-1]}", fixable=False) for repo, title, body in gaps] + \
           [Problem("blocker", line, fixable=False) for line in intake.repeated_blockers()]


STATE_STEP = "state"
OUTPUT_SUFFIXES = (".out", ".log", ".txt")
RETIRED_OUTPUTS = ("burndown.json", "gap-sweep-state.json", "sweep-state.json", "work-map-state.json")  # written by removed jobs under names that differ from theirs
UNREAD_STATE = ("684-close.md", "blocker-seen.json", "commands.log", "conform-due.json", "disabled-launchagents", "drain-*.out", "first-context.jsonl", "first-run.json",
                "fleet-staging", "fleet-sync.out", "groom-state.json*", "handoff-starts.json", "hookspath-watch.log", "inbox", "lesson-flags", "limits.json",
                "manager-edits.jsonl", "manager.json*", "migrations.json", "owner-decisions.jsonl*", "owner-morning.md", "owner-prompts.json", "owner-report.md", "pending-starts*",
                "retired-sessions.json", "retro.json", "structure-lessons.jsonl", "trace-checks.json", "trace.jsonl", "usage-profile.json", "validate-slots")  # names no code reads or writes (#1429)
PREFIX = "com.olivercode."
LOG_QUIET_SECONDS = 3600  # a log written more recently than this may have a live writer, so it waits for a quieter run


def _removed_outputs() -> set[str]:
    """The file names a removed job wrote: its name with each output suffix, plus the RETIRED_OUTPUTS."""
    from lib.cmd_install import REMOVED_JOBS
    return {label[len(PREFIX):] + suffix for label in REMOVED_JOBS for suffix in OUTPUT_SUFFIXES} | set(RETIRED_OUTPUTS)


def _free_lock(path: Path, remove: bool) -> bool:
    """True when no process holds the flock on this lock file, so the process that made it is gone. With remove, the free file is
    deleted while its lock is still held. A file another process holds, or one that cannot be read, is left alone."""
    try:
        with path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if remove:
                path.unlink(missing_ok=True)
            return True
    except OSError:
        return False


def _cut_log(path: Path, cap: int) -> None:
    """Keep the newest whole lines of a log within `cap` bytes. The file is rewritten in place, so a process that holds it open keeps its handle."""
    with path.open("rb") as handle:
        handle.seek(-(cap + 1), os.SEEK_END)  # one byte before the window says whether it starts on a line
        window = handle.read()
    kept = window[1:]
    if window[:1] != b"\n":
        kept = kept.split(b"\n", 1)[1] if b"\n" in kept else b""
    path.write_bytes(kept)


def _names(paths: list[Path]) -> str:
    return ", ".join(p.name for p in paths[:4]) + (" and more" if len(paths) > 4 else "")


def check_state(fix: bool, home: Path | None = None, limits: dict | None = None) -> list[Problem]:
    """The OliverCode home keeps only what is live. It reports each lock file no process holds, each output file of a removed job and
    each log over `stateLogBytes` in docs/LIMITS.json, with its count. With --fix it removes the locks and outputs and cuts the logs. A lock a live
    process holds is never touched."""
    from lib.health_checks import state_limits
    home = home or failure_log.home()
    cap = (state_limits() if limits is None else limits)["stateLogBytes"]
    found = []
    locks = [p for p in sorted(home.glob("*.lock")) if _free_lock(p, remove=fix)]
    if locks:
        found.append(Problem(STATE_STEP, f"{len(locks)} lock file(s) that no process holds: {_names(locks)}", fixable=True,
                             fixed=fix and not any(p.exists() for p in locks)))
    dead = [home / name for name in sorted(_removed_outputs()) if (home / name).is_file()]
    if dead:
        if fix:
            for path in dead:
                path.unlink(missing_ok=True)
        found.append(Problem(STATE_STEP, f"{len(dead)} output file(s) of removed jobs: {_names(dead)}", fixable=True,
                             fixed=fix and not any(p.exists() for p in dead)))
    unread = sorted({q for pattern in UNREAD_STATE for q in home.glob(pattern)})
    if unread:
        if fix:
            for path in unread:
                shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink(missing_ok=True)
        found.append(Problem(STATE_STEP, f"{len(unread)} file(s) no code reads: {_names(unread)}", fixable=True,
                             fixed=fix and not any(p.exists() for p in unread)))
    logs = sorted(p for p in home.iterdir() if p.suffix in (".log", ".out") and p.is_file()) if home.is_dir() else []
    quiet = [p for p in logs if time.time() - p.stat().st_mtime >= LOG_QUIET_SECONDS]  # a log still being written is cut by a later run
    big = [p for p in quiet if cap and p.stat().st_size > cap and p not in dead]
    if big:
        if fix:
            for path in big:
                _cut_log(path, cap)
        found.append(Problem(STATE_STEP, f"{len(big)} log(s) over {cap} bytes: {_names(big)}", fixable=True,
                             fixed=fix and not any(p.stat().st_size > cap for p in big)))
    return found


def run(fix: bool, cfg: placement.Config | None = None, health: bool = True) -> list[Problem]:
    fleet = None if cfg is None else []  # a caller's own config checks only its repoRoot, never this machine's private repos
    cfg = cfg or placement.config()
    problems = [*check_links(fix), *check_worktrees(cfg, fix), *check_branches(cfg, fix), *check_icloud(cfg, fix), *check_copies(cfg, fix),
                *check_git_sync(cfg, fix), *(check_main_checkout(fix) if fleet is None else []), *(check_outsiders(fix) if fleet is None else []), *(check_queues(fix) if fleet is None else []), *(check_suite(fix) if fleet is None else []), *(check_failure_gaps(fix) if fleet is None else []), *(check_state(fix) if fleet is None else []), *check_hooks_path(cfg, fix), *check_retired_jobs(fix), *check_job_python(), *check_tidy(cfg, fix), *check_synced(cfg, fleet), *check_placement(cfg), *check_docs(cfg), *check_worktree_hooks(cfg)]
    if health:  # health names what the steps above already named only once
        seen = {p.text for p in problems}
        problems += [p for p in check_health() if p.text not in seen]
    return problems


def _queue_decision(p: Problem) -> None:
    """Queue a problem only the owner can settle in the owner queue, once while it stays open."""
    from lib import cmd_owner
    step = f"maintain {p.step}: {p.text.splitlines()[0]}"
    if any(i["status"] == "open" and i["step"] == step for i in cmd_owner.items()):
        return
    cmd_owner.add("maintain", step)


def report(problems: list[Problem], fix: bool) -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"OliverCode maintain {stamp} ({'fixing' if fix else 'checking only'})",
             f"  interpreter: {sys.executable} ({sys.version_info[0]}.{sys.version_info[1]})"]
    left = 0
    for p in problems:
        if p.fixed:
            state = "FIXED"
        elif p.fixable and not fix:
            state = "FIXABLE (run with --fix)"
        else:
            state = "NEEDS A DECISION" if not p.fixable else "NOT FIXED"
        lines.append(f"  [{state}] {p.step}: {p.text}")
        if state == "NEEDS A DECISION":
            _queue_decision(p)
        if not p.fixed:
            left += 1
            failure_log.record("maintain", f"{p.step}: {p.text}", "machine")
    if not problems:
        lines.append("  [OK] nothing to repair")
    text = "\n".join(lines)
    if left:  # a run that leaves no failure prints nothing; the log still records it
        print(text)
    log = failure_log.home() / "maintenance.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    failure_log.append_private(log, text + "\n")
    failure_log.trim(log)
    return 1 if left else 0


def job_python() -> str:
    """The python3 the daily job runs: one that meets the minimum, else the system python3 so the job still installs."""
    if sys.version_info[:2] >= MIN_PYTHON:
        return sys.executable
    return newer_python() or shutil.which("python3") or "/usr/bin/python3"


def plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [job_python(), str(OC_ROOT / "scripts" / "olivercode"), "maintain", "--fix"],
        "StartCalendarInterval": {"Hour": 6, "Minute": 30},
        "StandardOutPath": str(failure_log.home() / "maintain.out"),
        "StandardErrorPath": str(failure_log.home() / "maintain.out"),
    }


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, plist, "daily maintenance job",
                            "`olivercode maintain --fix` runs daily at 06:30. Remove it with `olivercode maintain --unschedule`.")


def command_maintain(argv: list[str]) -> int:
    if argv == ["--schedule"]:
        return schedule(True)
    if argv == ["--unschedule"]:
        return schedule(False)
    if argv not in ([], ["--fix"]):
        print("Usage: olivercode maintain [--fix | --schedule | --unschedule]")
        return 1
    fix = argv == ["--fix"]
    for repo in dict.fromkeys([OC_ROOT, *_repos(placement.config())]):  # the daily run files the bugs each repo's failure and run logs hold, each read once by a fresh reader (#1371, #1397)
        try:
            with contextlib.redirect_stdout(io.StringIO()):  # a clean daily run prints nothing, and a failure still reaches stderr
                intake.bugs(repo)
        except Exception as exc:  # noqa: BLE001 -- bug intake never stops the daily repair
            print(f"maintain: bug intake for {repo.name} failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
    return report(run(fix), fix)
