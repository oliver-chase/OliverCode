#!/usr/bin/env python3
"""Claude Code SessionStart hook: tells the session, once, what would silently fail here.

`olivercode conform` only sees the repos in its registry and only when someone runs it.
This runs in every session, in whatever folder it starts, and names six gaps:

- the repo ships commit gates but git is not pointed at them (commits will be refused
  by commit_guard until it is fixed, so the session learns the fix up front)
- the repo is a git repo with no commit gates of its own
- a link that loads OliverCode's rules into ~/.claude is broken
- the repo's backlog has stories sitting in QA, which need their independent QA agent now
- a repo, worktree or backup sits outside repoRoot (scripts/lib/placement.py)
- the Mac is strained: a test runner has held a core for over an hour, or the load is far above the core count

It prints nothing when nothing is wrong, so a healthy session pays no context for it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import repo_gates  # noqa: E402

RULE_LINKS = ("CLAUDE.md", "VOICE.md")


def notes(cwd: Path, claude_dir: Path) -> list[str]:
    out = []
    for name in RULE_LINKS:
        link = claude_dir / name
        if link.is_symlink() and not link.exists():
            out.append(f"~/.claude/{name} is a broken link, so OliverCode's rules did not load. "
                       "Run `scripts/olivercode install` from the OliverCode folder.")
    out += placement_notes() + context_notes() + gh_notes()
    root = repo_gates.repo_root(cwd)
    if root:
        if repo_gates.has_gates(root):
            problem = repo_gates.gate_problem(root)
            if problem:
                out.append(f"In {root.name}, {problem}. Commits are refused until it is fixed: "
                           f"`git -C \"{root}\" config core.hooksPath .githooks`.")
        else:
            out.append(f"{root.name} has no commit gates of its own (no .githooks/pre-commit), "
                       "so nothing checks a commit here for secrets or broken rules.")
        queue = qa_queue(root)
        if queue:
            out.append(queue)
    return out


def placement_notes() -> list[str]:
    """One note naming the repos, worktrees and backups outside repoRoot, or nothing."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import placement
        stray = placement.findings()
    except Exception:  # noqa: BLE001 -- a placement bug never blocks a session
        return []
    if not stray:
        return []
    names = ", ".join(f"{f.path.name} ({f.kind})" for f in stray[:5]) + (f" and {len(stray) - 5} more" if len(stray) > 5 else "")
    return [f"{len(stray)} repo/worktree/backup item(s) sit outside repoRoot: {names}. "
            "Run `olivercode place` for the fix for each, and `olivercode clean` for merged worktrees."]


def context_notes() -> list[str]:
    """A note when the files a session loads at start exceed the contextWords budget, else nothing."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib import context_budget
        ok, text = context_budget.report(None)
    except Exception:  # noqa: BLE001 -- a budget bug never blocks a session
        return []
    return [] if ok else [text.replace("\n", " ")]


def gh_notes() -> list[str]:
    """A note while the shared GitHub rate-limit hold is on, else nothing."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
        import gh_budget
        why = gh_budget.refusal()
    except Exception:  # noqa: BLE001 -- never blocks a session
        return []
    return [why] if why else []


def qa_queue(root: Path, run=subprocess.run) -> str:
    """Names the stories a repo's Project holds in QA, or nothing when it has no backlog config, no gh or no answer in 8 seconds."""
    config = root / "docs" / "backlog-config.json"
    try:
        cfg = json.loads(config.read_text())
        done = run(["gh", "project", "item-list", str(cfg["projectNumber"]), "--owner", cfg["projectOwner"],
                    "--limit", "400", "--format", "json"], capture_output=True, text=True, timeout=8)
        items = json.loads(done.stdout)["items"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return ""
    stuck = sorted(i["content"]["number"] for i in items if i.get("status") == "QA" and i.get("content", {}).get("number"))
    if not stuck:
        return ""
    return (f"{root.name} has {len(stuck)} stor{'y' if len(stuck) == 1 else 'ies'} waiting in QA "
            f"({', '.join('#' + str(n) for n in stuck)}). Start an independent QA agent for them now: it logs its verdict, "
            "then the story moves to Complete on a pass or back to In Progress on a fail.")

RUNNERS = ("vitest", "jest", "pytest", "unittest")


def machine_strain(ps_text: str, load: float, cores: int) -> list[str]:
    """Names test runners that ran over an hour at over 50% CPU, and a load above 1.5 times the core count."""
    out = []
    for line in ps_text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not any(r in parts[3] for r in RUNNERS):
            continue
        pid, cpu, etime, command = parts
        try:
            hours = _hours(etime)
            busy = float(cpu) > 50
        except ValueError:
            continue
        if hours >= 1 and busy:
            out.append(f"A test runner (pid {pid}, `{command[:60]}`) has run for {etime} at {cpu}% CPU. "
                       f"If no session of yours is using it, stop it with `kill {pid}`.")
    if cores and load > 1.5 * cores:
        out.append(f"The Mac's load is {load:.1f} on {cores} cores, so content-flow jobs may time out. "
                   "Hold heavy runs until it falls.")
    return out


def _hours(etime: str) -> float:
    """Converts ps elapsed time ([[dd-]hh:]mm:ss) to hours."""
    days, _, rest = etime.rpartition("-")
    nums = [int(x) for x in rest.split(":")]
    while len(nums) < 3:
        nums.insert(0, 0)
    return int(days or 0) * 24 + nums[0] + nums[1] / 60 + nums[2] / 3600


def live_strain(run=subprocess.run) -> list[str]:
    """Reads the process table and load average; any failure means no note."""
    try:
        ps = run(["ps", "-Ao", "pid=,pcpu=,etime=,command="], capture_output=True, text=True, timeout=5).stdout
        return machine_strain(ps, os.getloadavg()[0], os.cpu_count() or 0)
    except (OSError, subprocess.SubprocessError):
        return []


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    found = notes(Path(data.get("cwd") or "."), Path.home() / ".claude") + live_strain()
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": "OliverCode session check: " + " ".join(found)}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- a broken check must never stop a session from starting
        raise SystemExit(0)
