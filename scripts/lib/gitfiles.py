"""The one git helper every module calls (#1457), and the reader of `git ls-files` for the checks that list a repo's files."""
from __future__ import annotations

import subprocess
from pathlib import Path


def run(repo: Path, *args: str, timeout: float | None = None, env: dict | None = None, text: bool = True) -> subprocess.CompletedProcess:
    """`git -C REPO ARGS` with its output captured. A timeout or a missing git is returncode 124 with the reason in stderr, so one slow repo is a failed row
    and never a crash of the whole run. text=False returns bytes."""
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env,
                              **({"text": True, "errors": "replace"} if text else {}))
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(["git", *args], 124, "" if text else b"", f"git {args[0] if args else ''} did not finish: {exc}" if text else b"")


def out(repo: Path, *args: str, timeout: float | None = None, env: dict | None = None, check: bool = False) -> str:
    """The stdout of `git -C REPO ARGS` with its trailing newline kept, or '' when git fails. check=True raises CalledProcessError on a failure."""
    done = run(repo, *args, timeout=timeout, env=env)
    if check and done.returncode:
        raise subprocess.CalledProcessError(done.returncode, done.args, done.stdout, done.stderr)
    return done.stdout if done.returncode == 0 else ""


def tracked_files(repo_root: Path, *args: str) -> list[str]:
    """The paths `git ls-files ARGS` prints for the repo, or an empty list when git fails."""
    out = subprocess.run(["git", "-C", str(repo_root), "ls-files", *args], capture_output=True, text=True, check=False)
    return [line for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []


def changed_paths(repo: Path, *paths: str) -> list[str]:
    """Every path git status shows as modified, staged, deleted or untracked, limited to PATHS when given."""
    lines = run(repo, "status", "--porcelain", "--untracked-files=all", *(["--", *paths] if paths else [])).stdout.splitlines()
    return [line[3:].split(" -> ")[-1].strip('"') for line in lines]


def commit_changes(repo: Path, paths: list[str], message: str) -> str:
    """The one commit helper for adoption commands (#775): commit PATHS with MESSAGE in one commit and say what happened.

    Never pushes and never skips the repo's own hooks: a refusal is reported and the paths are unstaged."""
    if run(repo, "rev-parse", "-q", "--verify", "HEAD").returncode != 0:
        return "not committed, the repo has no commits"
    if not paths:
        return "nothing to commit"
    present = [p for p in paths if (repo / p).exists()]  # a deleted path is committed by name below
    added = run(repo, "add", "-A", "--", *present) if present else subprocess.CompletedProcess([], 0, "", "")
    done = added if added.returncode else run(repo, "commit", "-q", "-m", message, "--", *paths)
    if done.returncode:
        run(repo, "reset", "-q", "--", *paths)
        lines = (done.stderr or done.stdout).strip().splitlines()
        why = "git add failed" if added.returncode else "the repo's own gates refused it"
        return f"not committed, {why}" + (f" ({lines[0].strip()})" if lines else "")
    return f"committed {run(repo, 'rev-parse', '--short', 'HEAD').stdout.strip()}"


def commit_after(repo: Path, change, subject: str, body: str, touches: tuple[str, ...] | None = None) -> str:
    """Run CHANGE (a callable that edits files in REPO) and commit every file it changed in one commit.

    A repo whose local changes overlap TOUCHES (any local change when TOUCHES is None) is skipped before CHANGE runs.
    Local changes elsewhere stay out of the commit."""
    has_head = run(repo, "rev-parse", "-q", "--verify", "HEAD").returncode == 0
    before = set(changed_paths(repo)) if has_head else set()
    clash = sorted(before if touches is None else {p for p in before if any(p == t or p.startswith(t.rstrip("/") + "/") for t in touches)})
    if clash:
        return f"not committed, {', '.join(clash[:3])}{' and more' if len(clash) > 3 else ''} already had uncommitted changes"
    change()
    message = f"{subject}\n\n{body}\n\nNo test: files written by an OliverCode adoption command\nSize: XS\n"
    return commit_changes(repo, [p for p in changed_paths(repo) if p not in before], message)
