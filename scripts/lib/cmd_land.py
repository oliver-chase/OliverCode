"""Launcher command `land`: `olivercode land WORKTREE STORY` puts a story's commit on origin/main (#608).

It rebases the worktree on origin/main, squashes a branch of several commits into one whose message is the first commit's title and the story number (#898), runs the repo's validation up to twice unless a passing run already recorded the same tree (#910), pushes HEAD:main and retries up to four times when main moves. After a push it fast-forwards the main
checkout when that is clean and prints how far behind an edited or diverged one is. The log is ~/.olivercode/land/land-REPO-N.log (under OLIVERCODE_HOME when set) and ends
with `RESULT pushed SHA`, `RESULT rebase-conflict`, `RESULT validate-failed`, `RESULT push-failed` (the push failed while main stood still) or `RESULT main-kept-moving` (a land keeps retrying with a short pause for ten minutes while main moves and each rebase is clean). A second land for a story that is already running refuses. Land never edits docs/LIMITS.json: the size ceiling only warns (#879).

A landed story is cleaned up here (#712): the worktree, the local branch and the remote branch are deleted, so no session needs a removal permission. Work that did not land
stays in its worktree, gets a handover file ~/.olivercode/land/handover-REPO-N.md, and no branch is pushed for it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from lib import agent_loop, failure_log, maintain, validated
from lib.validate_gates import PROGRESS  # the lines that also print on the terminal while a land validates (#776)
from lib.local_config import OC_ROOT

LOG_DIR: Path | None = None  # None means failure_log.home() / "land", which belongs to the user running it
TRIES = 4
BUDGET = 600  # seconds a land keeps retrying after TRIES clean rebases while main keeps moving (#784)
PAUSE = 5
USAGE = "Usage: olivercode land WORKTREE STORY"
CUT_LOCK = "version-cut.lock"


def _run(wt: Path, log, *cmd: str, env: dict | None = None) -> bool:
    try:
        return subprocess.run(cmd, cwd=wt, stdout=log, stderr=log, env=env).returncode == 0
    except OSError as exc:
        log.write(f"{cmd[0]}: {exc}\n")
        return False


def _validate_once(wt: Path, log, say=print) -> bool:
    """One validation run: every line goes to the log, and each gate's start, finish and budget line also prints at that moment."""
    try:
        proc = subprocess.Popen(agent_loop.validation_command(wt) or ["false"], cwd=wt, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace")
    except OSError as exc:
        log.write(f"validate: {exc}\n")
        return False
    for line in proc.stdout:
        log.write(line)
        if line.startswith(PROGRESS):
            say(line.rstrip("\n"), flush=True)
    return proc.wait() == 0


def _validates(wt: Path, log) -> bool:
    for _ in range(2):
        if _validate_once(wt, log):
            return True
        log.write("--- validate failed, rerun\n")
        log.flush()
    return False


def _reuses_pass(wt: Path, log) -> bool:
    """True when the tree this attempt would push has a recent passing validation on record, so the runner's pass stands and land skips
    its own run (#910). A rebase that changed the tree has no record, so it is validated again."""
    tree = _git(wt, "rev-parse", "HEAD^{tree}").stdout.strip()
    row = validated.recorded_pass(tree) if tree else None
    if row is None:
        return False
    log.write(f"--- tree {tree[:12]} passed validation at {row['time']}, so land reuses that record and does not validate again\n")
    return True


def link_venv(main: Path, wt: Path) -> bool:
    """Link the main checkout's .venv into a new worktree so validation finds the repo's interpreter (#752). Returns True when it linked.
    A repo with no .venv, or a worktree that already has one, is left alone."""
    source, target = main / ".venv", wt / ".venv"
    if not source.is_dir() or target.exists() or target.is_symlink():
        return False
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        return False
    return True


def prepare_worktree(wt: Path, main: Path | None = None) -> list[str]:
    """Make a worktree accept its first commit (#786): hooksPath set for this worktree alone (plain `git config` does not override
    config.worktree), the hooks built, the virtualenv linked. Returns what failed, each with its words."""
    main, problems = main or _main_checkout(wt), []
    if main and main != wt:
        link_venv(main, wt)
    builder = wt / "scripts" / "build-hooks.py"
    if builder.is_file() and subprocess.run([sys.executable, str(builder)], cwd=wt, capture_output=True).returncode:
        problems.append("scripts/build-hooks.py failed, so the hooks are not built")
    if _git(wt, "config", "extensions.worktreeConfig", "true").returncode or _git(wt, "config", "--worktree", "core.hooksPath", ".githooks").returncode:
        problems.append("git would not set core.hooksPath for this worktree")
    return problems


def add_worktree(repo: Path, wt: Path, n: str, base: str = "") -> list[str]:
    """`olivercode worktree add N`: create story/N from base, then prepare it. Returns what failed, empty when it is ready to commit."""
    base = base or f"origin/{default_branch(repo)}"
    made = subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", f"story/{n}", base], capture_output=True, text=True)
    if made.returncode:
        return [f"the worktree was not created: {(made.stderr or made.stdout).strip()}"]
    return prepare_worktree(wt, repo)


RESUME_NOTE = ("Earlier partial work is present on branch story/{n}. Run `git status` and `git log` first, check what the earlier session already did, "
               "and continue from it without redoing it.")


def resume_worktree(repo: Path, wt: Path, n: str, base: str = "") -> tuple[list[str], str]:
    """Make story/N's worktree for a builder (#877). A fresh story gets a new branch from base. When the branch or worktree already exists
    (an earlier session stopped), the branch is reused: the worktree is attached when missing, commits and uncommitted changes stay, and the
    branch is rebased onto base when that is clean. Returns (problems, note for the builder's brief), the note empty for a fresh story."""
    base = base or f"origin/{default_branch(repo)}"
    first = add_worktree(repo, wt, n, base)
    if not first or "already" not in first[0]:
        return first, ""
    branch = f"story/{n}"
    if not (wt / ".git").exists():
        _git(repo, "worktree", "prune")
        made = _git(repo, "worktree", "add", str(wt), branch)
        if made.returncode:
            return [f"the worktree was not attached to {branch}: {(made.stderr or made.stdout).strip()}"], ""
    problems = prepare_worktree(wt, repo)
    note = RESUME_NOTE.format(n=n)
    if _git(wt, "merge-base", "--is-ancestor", base, "HEAD").returncode == 0:
        return problems, note
    if _git(wt, "rebase", "--autostash", base).returncode:
        _git(wt, "rebase", "--abort")
        note += f" The branch conflicts with {base}, so it was left where it was and not rebased."
    else:
        note += f" The branch was rebased onto {base}."
    return problems, note


def default_branch(wt: Path) -> str:
    return agent_loop.default_branch(wt)


def _main_checkout(wt: Path) -> Path | None:
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common).parent if common else None


def squash(wt: Path, story: str, log) -> bool:
    """Replace a branch's commits on top of origin/main with one commit holding the same tree, so main gains one commit per story (#898).
    Its message is the first commit's subject with the story number. A branch of one commit keeps its own message. Returns False when the squash failed."""
    subjects = _git(wt, "log", "--reverse", "--format=%s", f"origin/{default_branch(wt)}..HEAD").stdout.splitlines()
    if len(subjects) < 2:
        return True
    title = re.sub(r"\s*\(#\d+\)\s*$", "", subjects[0]).strip() or f"Story {story}"
    tree = _git(wt, "rev-parse", "HEAD^{tree}").stdout.strip()
    made = _git(wt, "commit-tree", tree, "-p", f"origin/{default_branch(wt)}", "-m", f"{title} (#{story})")
    new = made.stdout.strip()
    if made.returncode or not new or _git(wt, "reset", "--soft", new).returncode:
        log.write(f"--- squash failed: {made.stderr.strip()}\n")
        return False
    log.write(f"--- squashed {len(subjects)} commits into {new[:8]}\n")
    return True


def refusal(wt: Path) -> tuple[str, str]:
    """(result word, message) when wt must not land: it holds uncommitted files, which the push would leave behind, or it has no validation command,
    which no run can pass (#1011). ("", "") when it may land."""
    dirty = [line[3:] for line in _git(wt, "status", "--porcelain").stdout.splitlines() if line.strip()]
    if dirty:
        return "dirty-worktree", f"Refused: {wt} has uncommitted files, so nothing landed: {', '.join(dirty[:10])}. Commit them by explicit path or remove them."
    if agent_loop.validation_command(wt) is None:
        return "no-validate", f"Refused: {wt} has no validation command, so nothing can check the commit and it is not read as done. Fix: {agent_loop.NO_VALIDATION_FIX}"
    return "", ""


def land(wt: Path, story: str, log) -> tuple[str, str]:
    """Run the landing recipe in wt, writing to log. Returns (result word, short sha)."""
    word, why = refusal(wt)
    if word:
        log.write(why + "\n")
        return word, ""
    main = _main_checkout(wt)
    if main and main != wt and link_venv(main, wt):
        log.write(f"linked {main / '.venv'} into {wt}\n")
    base = default_branch(wt)
    deadline, attempt = time.monotonic() + BUDGET, 0
    while attempt < TRIES or time.monotonic() < deadline:
        if attempt >= TRIES:
            log.write("--- main moved again, waiting to retry\n")
            log.flush()
            time.sleep(PAUSE)
        attempt += 1
        _run(wt, log, "git", "fetch", "-q", "origin")
        if not _run(wt, log, "git", "rebase", f"origin/{base}"):
            _run(wt, log, "git", "rebase", "--abort")
            return "rebase-conflict", ""
        if not squash(wt, story, log):
            return "push-failed", ""
        if not _reuses_pass(wt, log) and not _validates(wt, log):
            return "validate-failed", ""
        _run(wt, log, "git", "fetch", "-q", "origin")
        if not _run(wt, log, "git", "merge-base", "--is-ancestor", f"origin/{base}", "HEAD"):
            continue
        if _run(wt, log, "git", "push", "origin", f"HEAD:{base}"):
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
            return "pushed", sha
        _run(wt, log, "git", "fetch", "-q", "origin")
        if _run(wt, log, "git", "merge-base", "--is-ancestor", f"origin/{base}", "HEAD"):
            return "push-failed", ""  # main did not move, so the push error in the log is the reason (#851)
    return "main-kept-moving", ""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def cleanup(wt: Path) -> list[str]:
    """Delete a landed story's worktree, local branch and remote branch. Returns one line per thing removed or kept and why.
    Nothing is removed while the worktree has uncommitted changes or a commit that is not on origin/main, and main is never touched."""
    branch = _git(wt, "branch", "--show-current").stdout.strip()
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not common or _git(wt, "merge-base", "--is-ancestor", "HEAD", f"origin/{default_branch(wt)}").returncode != 0:
        return [f"Kept {wt}: it has commits that are not on origin/{default_branch(wt)}."]
    if _git(wt, "status", "--porcelain").stdout.strip():
        return [f"Kept {wt}: it has uncommitted changes."]
    lines = []
    gone = _git(Path(common), "worktree", "remove", str(wt))
    lines.append(f"Removed worktree {wt}." if gone.returncode == 0 else f"Kept {wt}: {gone.stderr.strip()[:100]}")
    if gone.returncode != 0 or not branch or branch in {"main", "master", "develop"}:
        return lines
    if _git(Path(common), "branch", "-D", branch).returncode == 0:
        lines.append(f"Deleted local branch {branch}.")
    if _git(Path(common), "ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0:
        done = _git(Path(common), "push", "origin", "--delete", branch)
        lines.append(f"Deleted remote branch {branch}." if done.returncode == 0 else f"Remote branch {branch} stays: {done.stderr.strip()[:100]}")
    return lines


def write_handover(wt: Path, story: str, result: str, log_path: Path, key: str = "") -> Path:
    """The file a session leaves for work that did not land. It names the worktree and the result, so the next session finishes or discards the story."""
    branch = _git(wt, "branch", "--show-current").stdout.strip() or "detached"
    path = log_path.parent / f"handover-{key or story}.md"
    path.write_text(f"# Story #{story} did not land\n\nResult: {result}\nWorktree: {wt}\nBranch: {branch} (local only, never pushed)\nLog: {log_path}\n\n"
                    f"Next: fix the cause in the worktree and run `olivercode land {wt} {story}`, or discard the story with its reason on the issue.\n")
    return path


def _repo_name(wt: Path) -> str:
    main = _main_checkout(wt)
    return (main or wt).name


def log_dir() -> Path:
    return LOG_DIR or failure_log.home() / "land"


def live_pid(lock: Path) -> int | None:
    """The pid a lock file names when that process is alive and is not this one."""
    try:
        pid = int(lock.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return None if pid == os.getpid() else pid


def cut_running(directory: Path) -> int | None:
    return live_pid(directory / CUT_LOCK)


def _holder(lock: Path) -> int | None:
    """The pid in the lock when that process is still alive, else None. A lock that is still empty is being written, so it is read again before it counts as gone."""
    for _ in range(5):
        try:
            pid = int(lock.read_text().strip())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.05)
            continue
        try:
            os.kill(pid, 0)
        except PermissionError:
            return pid  # alive, owned by another user
        except OSError:
            return None
        return pid
    return None


def _claim(lock: Path) -> int | None:
    """Take the story's lock. Returns the pid of a land that still holds it, or None once the lock is ours (#880).
    The file is created exclusively (O_CREAT|O_EXCL), so of two lands that claim at once only one creates it and the other reads the holder.
    A lock whose pid is gone is removed and created again."""
    for _ in range(3):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = _holder(lock)
            if pid:
                return None if pid == os.getpid() else pid
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        return None
    return _holder(lock) or -1


def command_land(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0].startswith("-") or not argv[1].lstrip("#").isdigit() or not (Path(argv[0]) / ".git").exists():
        print(USAGE)
        return 2
    wt, story = Path(argv[0]).resolve(), argv[1].lstrip("#")
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    while cut_running(folder):  # a land waits until a running version cut finishes (#789)
        time.sleep(PAUSE)
    key = f"{_repo_name(wt)}-{story}"
    path = folder / f"land-{key}.log"
    lock = folder / f"land-{key}.lock"
    running = _claim(lock)
    if running:
        print(f"A land for story #{story} is already running (pid {running}). Its log: {path}")
        return 1
    try:
        with path.open("w") as log:
            result, sha = land(wt, story, log)
            line = f"RESULT {result} {sha}".strip()
            log.write(line + "\n")
    finally:
        lock.unlink(missing_ok=True)
    print(f"{line} (log: {path})")
    if result in ("dirty-worktree", "no-validate"):
        print(refusal(wt)[1])
    if result != "pushed":
        print(f"Handover written to {write_handover(wt, story, result, path, key)}. No branch was pushed.")
        return 1
    root, branch = _main_checkout(wt) or OC_ROOT, default_branch(wt)  # read before cleanup removes the worktree
    for line in cleanup(wt):
        print(line)
    behind, state, moved = maintain.fast_forward(root, fetch=True, branch=branch)  # the story's own repo, never OliverCode's checkout (#1012)
    if moved:
        print(f"Main checkout fast-forwarded {behind} commit(s).")
    elif behind:
        print(f"Main checkout left alone: {behind} commit(s) behind origin/{branch} and {state}.")
    return 0
