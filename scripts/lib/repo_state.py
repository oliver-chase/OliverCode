"""Whether GitHub has archived a repo, so no command or hook touches it.

An archived repo accepts no push, so a commit made there can never leave the machine. `archived(path)` asks GitHub once per repo and remembers the answer for a day in
~/.olivercode/repo-state.json (gh_budget.home(), the folder the other shared state uses). A repo with no
GitHub origin, and any failure to ask (offline, auth, rate limit), answers None and is not remembered, so
the helper fails open and never blocks work on its own trouble. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from lib import gh_budget
except ImportError:  # run from scripts/lib itself, as the other shared-state modules are
    import gh_budget  # type: ignore[no-redef]

TTL_SECONDS = 24 * 3600
OFF_ENV = "OLIVERCODE_ARCHIVED"  # "off" skips every lookup; the test harness sets it so no test reaches GitHub
FILE = "repo-state.json"
GITHUB_ORIGIN = re.compile(r"github\.com[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$")
_said: set[str] = set()


def _gh(args: list[str]) -> tuple[int, str, str]:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=20)
    return done.returncode, done.stdout, done.stderr


def origin(repo_path: Path | str) -> str | None:
    """`owner/name` of the checkout's GitHub origin, or None when it has no GitHub origin."""
    try:
        done = subprocess.run(["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    found = GITHUB_ORIGIN.search(done.stdout.strip()) if done.returncode == 0 else None
    return f"{found.group(1)}/{found.group(2)}" if found else None


def _cache() -> dict:
    try:
        data = json.loads((gh_budget.home() / FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(slug: str, state: str, now: float) -> None:
    try:
        entries = _cache()
        entries[slug] = {"state": state, "at": now}
        gh_budget.home().mkdir(parents=True, exist_ok=True)
        whole = gh_budget.home() / (FILE + ".tmp")
        whole.write_text(json.dumps(entries) + "\n", encoding="utf-8")
        os.replace(whole, gh_budget.home() / FILE)
    except OSError:
        pass  # an unwritable cache only costs the next call another lookup


def archived(repo_path: Path | str, runner=None, clock=time.time) -> str | None:
    """"archived" when GitHub says so, else None. `runner(args)` returns (code, stdout, stderr)."""
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return None
    slug = origin(repo_path)
    if not slug:
        return None
    now = clock()
    hit = _cache().get(slug)
    # A "deleted" entry from an older version is ignored: it may have been a wrong account or no access (#691).
    if isinstance(hit, dict) and hit.get("state") in ("active", "archived") and now - float(hit.get("at", 0)) < TTL_SECONDS:
        return None if hit.get("state") == "active" else hit.get("state")
    try:
        code, out, err = (runner or _gh)(["repo", "view", slug, "--json", "isArchived"])
    except (OSError, subprocess.SubprocessError):
        return None
    if code != 0:
        # "Could not resolve to a repository" is also what GitHub says for the wrong account or no access, so it is
        # not proof of deletion. It answers None and is never cached, so it cannot block every commit for a day (#691).
        return None
    try:
        flag = json.loads(out)["isArchived"]
    except (ValueError, KeyError, TypeError):
        return None
    state = "archived" if flag is True else "active"
    _remember(slug, state, now)
    return None if state == "active" else state


def skip_line(name: str, state: str) -> str:
    return f"skip {name}: {state} on GitHub"


def skipped(name: str, repo_path: Path | str, out=print, runner=None) -> bool:
    """True when the repo is archived or deleted; says so once per repo per process, on `out`."""
    state = archived(repo_path, runner=runner)
    if not state:
        return False
    if str(repo_path) not in _said:
        _said.add(str(repo_path))
        out(f"  {skip_line(name, state)}")
    return True


def forget_said() -> None:
    _said.clear()


if __name__ == "__main__":
    # `repo_state.py [DIR]` prints the state of one checkout, for a quick look.
    print(archived(sys.argv[1] if len(sys.argv) > 1 else ".") or "active")
