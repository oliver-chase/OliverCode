"""Scheduled tasks and launchd jobs: every path they name must exist, be tracked and name a live repo.

A scheduled task (~/.claude/scheduled-tasks/NAME/SKILL.md) or a launchd job (~/Library/LaunchAgents/*.plist)
that points at a moved script or a retired repo fails on every run and nobody sees it. `check()` reads both,
pulls out the absolute and ~-relative paths, and reports a FAIL for a missing path, a retired name or an
archived or deleted repo, and a WARN for a script no repo tracks. It also WARNs when a task's last three runs
all ended interrupted or failed. Run history is read from the Claude desktop app's session files, one per run,
or from an injected source. Standard library only; GitHub is asked only through repo_state's daily cache.
"""

from __future__ import annotations

import json
import plistlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from lib import gitfiles, repo_state
from lib.local_config import load_local

THIRD_PARTY = ("com.google.", "com.apple.", "com.microsoft.", "com.adobe.", "org.mozilla.")
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl", ".command"}
OUTPUT_SUFFIXES = {".log", ".out", ".err"}
SYSTEM_PREFIXES = ("/bin/", "/sbin/", "/usr/", "/dev/", "/tmp/", "/etc/", "/var/", "/opt/", "/private/",
                   "/System/", "/Library/", "/Applications/")
LAST_RUNS = 3
PATH = re.compile(r"(?<![\w:./~$-])(~/|/)[A-Za-z0-9_.@+\-/]+")
SPACED = re.compile(r" ([A-Za-z0-9_.@+\-][A-Za-z0-9_.@+\-/]*)")


@dataclass
class Finding:
    level: str  # "FAIL" or "WARN"
    task: str
    text: str


@dataclass
class Run:
    at: float
    state: str  # "ok", "interrupted" or "failed"


def sessions_dir() -> Path:
    return Path(os.environ.get("OLIVERCODE_SESSIONS_DIR") or Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions")


def settings() -> dict:
    return load_local().get("schedules", {})


def retired_names() -> tuple[str, ...]:
    return tuple(settings().get("retiredNames", ()))


def label_prefixes() -> tuple[str, ...]:
    return tuple(settings().get("labelPrefixes", ()))


def paths_in(text: str, home: Path | None = None) -> list[str]:
    """Absolute and ~-relative paths named in the text, expanded, in order, without repeats."""
    home = home or Path.home()
    found: list[str] = []
    for m in PATH.finditer(text):
        raw, end = m.group(0), m.end()
        # A folder name with a space ("Notes Vault") ends the match early, so extend it across a space
        # while the longer folder exists on disk.
        while True:
            nxt = SPACED.match(text, end)
            if not nxt:
                break
            head = raw + " " + nxt.group(1).split("/")[0]
            full = str(home / head[2:]) if head.startswith("~/") else head
            if not os.path.exists(full):
                break
            raw, end = raw + " " + nxt.group(1), nxt.end()
        if text[end:end + 1] in ("*", "<", "{", "$", "["):
            continue
        raw = raw.rstrip(".,;:)'\"/")
        if raw in ("~", "/", "~/"):
            continue
        path = str(home / raw[2:]) if raw.startswith("~/") else raw
        if path.startswith(SYSTEM_PREFIXES) and not path.startswith(str(home) + "/"):
            continue
        if path not in found:
            found.append(path)
    return found


def _is_output(path: Path) -> bool:
    return path.suffix in OUTPUT_SUFFIXES and path.parent.is_dir()


def _plist_paths(data: dict, home: Path) -> list[str]:
    values = [str(a) for a in data.get("ProgramArguments", [])]
    values.append(str(data.get("WorkingDirectory", "")))
    values += [str(v) for v in data.get("EnvironmentVariables", {}).values()]
    return [p for v in values for p in paths_in(" " + v, home)]


def _ours(label: str, paths: list[str], home: Path, prefixes: tuple[str, ...]) -> bool:
    if label.startswith(prefixes) if prefixes else False:
        return True
    if label.startswith(THIRD_PARTY):
        return False
    library = str(home / "Library")
    return any(p.startswith(str(home) + "/") and not p.startswith(library + "/") for p in paths)


def jobs(tasks_dir: Path, agents_dir: Path, home: Path, prefixes: tuple[str, ...]) -> list[tuple[str, str, list[str]]]:
    """(name, raw text, paths) for each scheduled task and each launchd job that is ours."""
    found = []
    for skill in sorted(tasks_dir.glob("*/SKILL.md")) if tasks_dir.is_dir() else []:
        text = skill.read_text(encoding="utf-8", errors="replace")
        found.append((skill.parent.name, text, paths_in(text, home)))
    for plist in sorted(agents_dir.glob("*.plist")) if agents_dir.is_dir() else []:
        try:
            data = plistlib.loads(plist.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        label = str(data.get("Label", plist.stem))
        paths = _plist_paths(data, home)
        if _ours(label, paths, home, prefixes):
            found.append((label, plist.read_text(encoding="utf-8", errors="replace"), paths))
    return found


def _classify(session: dict) -> str | None:
    """"ok", "interrupted" or "failed" for a finished run of a scheduled task, None for one still running."""
    summary = session.get("postTurnSummary") or {}
    if session.get("error") or summary.get("status_category") == "blocked":
        return "failed"
    if session.get("lastTurnCutShort"):
        return "interrupted"
    if summary.get("status_category") or session.get("completedTurns"):
        return "ok"
    return None


def task_runs(directory: Path | None = None) -> dict[str, list[Run]] | None:
    """Runs per scheduled task id, oldest first, read from the desktop app's session files. None when there are none to read."""
    directory = directory or sessions_dir()
    if not directory.is_dir():
        return None
    runs: dict[str, list[Run]] = {}
    for f in directory.glob("*/*/local_*.json"):
        try:
            session = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        task = session.get("scheduledTaskId") if isinstance(session, dict) else None
        state = _classify(session) if task else None
        if task and state:
            runs.setdefault(task, []).append(Run(float(session.get("createdAt", 0)), state))
    for lst in runs.values():
        lst.sort(key=lambda r: r.at)
    return runs


def task_crons(directory: Path | None = None) -> dict[str, tuple[str, bool]] | None:
    """(cron expression, enabled) per scheduled task id, from the desktop app's scheduled-tasks.json. None when there is none to read."""
    directory = directory or sessions_dir()
    if not directory.is_dir():
        return None
    crons: dict[str, tuple[str, bool]] = {}
    for f in directory.glob("*/*/scheduled-tasks.json"):
        try:
            tasks = json.loads(f.read_text(encoding="utf-8")).get("scheduledTasks", [])
        except (OSError, ValueError, AttributeError):
            continue
        for t in tasks:
            if isinstance(t, dict) and t.get("id") and t.get("cronExpression"):
                crons[t["id"]] = (str(t["cronExpression"]), t.get("enabled", True) is not False)
    return crons


def _cron_count(field: str, low: int, high: int, wrap: int = 0) -> int:
    """How many values one cron field (`*`, `*/n`, `a-b`, `a-b/n`, `a,b`) matches between low and high."""
    values: set[int] = set()
    for part in field.split(","):
        rng, _, step = part.partition("/")
        step_n = int(step) if step.isdigit() and int(step) > 0 else 1
        if rng in ("*", ""):
            a, b = low, high
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-", 1))
        else:
            a = b = int(rng)
            if step:
                b = high
        values.update(range(a, b + 1, step_n))
    return len({v % wrap if wrap else v for v in values if low <= v <= high})


def runs_per_day(cron: str) -> float | None:
    """Average runs per day of a five-field cron expression, None when it cannot be read. A weekday or day-of-month limit
    scales the count by its share of the week or month."""
    fields = cron.split()
    if len(fields) != 5:
        return None
    try:
        per_day = _cron_count(fields[0], 0, 59) * _cron_count(fields[1], 0, 23)
        if fields[2] != "*":
            per_day *= _cron_count(fields[2], 1, 31) / 30
        if fields[3] != "*":
            per_day *= _cron_count(fields[3], 1, 12) / 12
        if fields[4] != "*":
            per_day *= _cron_count(fields[4], 0, 7, wrap=7) / 7
    except ValueError:
        return None
    return per_day


# A gate is a script that finds out whether there is work before a model starts. A job names one when it says "gate" or runs `olivercode gated` (#998).
GATE_WORDS = re.compile(r"\bgated?\b", re.IGNORECASE)
MODEL_START = re.compile(r"(^|[/<>\s])claude(\s|<|$)")


def ungated(tasks_dir: Path, crons: dict[str, tuple[str, bool]] | None) -> list[tuple[str, float | None]]:
    """(task, runs per day) for each enabled recurring scheduled task whose prompt names no gate command."""
    out = []
    for name, (cron, enabled) in sorted((crons or {}).items()):
        skill = tasks_dir / name / "SKILL.md"
        if not enabled or not skill.is_file():
            continue
        if not GATE_WORDS.search(skill.read_text(encoding="utf-8", errors="replace")):
            out.append((name, runs_per_day(cron)))
    return out


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    for parent in (probe, *probe.parents):
        if (parent / ".git").exists():
            return parent
    return None


REFRESH_WORDS = re.compile(r"republish|refresh|\bpublish\b|artifact tool|dashboard", re.IGNORECASE)
PAGE_WORDS = re.compile(r"dashboard|\bpage\b|artifact|work ?map", re.IGNORECASE)
TOKEN_FREE_HINT = ("Run the build from a launchd job that starts no Claude session and have the page read its data at view time "
                   "so no token is spent per refresh.")


GATE_HINT = ("Put a gate script first that exits when there is no work, and start the model only when it finds some "
             "(baseline rule 17 in skills/skill-creation/SKILL.md).")


def _launchd_rate(text: str) -> str:
    """A launchd job's runs per day in words, from its StartInterval or StartCalendarInterval."""
    try:
        data = plistlib.loads(text.encode("utf-8"))
    except (ValueError, plistlib.InvalidFileException):
        return "an unknown number of times"
    cal = data.get("StartCalendarInterval")
    per_day = 86400 / data["StartInterval"] if data.get("StartInterval") else (len(cal) if isinstance(cal, list) else 1) if cal else None
    if per_day is None:
        return "an unknown number of times" if not data.get("RunAtLoad") else "once"
    return f"{round(per_day, 2):g} time{'s' if per_day != 1 else ''}"


def gate_fix(text: str, is_task: bool, name: str) -> str:
    """The fix for an ungated job: the exact `olivercode gated` line to put in its place, where CHECK exits 0 with work and 1 with none."""
    from lib import gated
    return f"Put this in its place, with CHECK a script that exits 0 when there is work and 1 when there is none: `{gated.wrapper_line(text, is_task, name)}`."


def refusal(label: str, plist: dict) -> str | None:
    """Why a launchd job is not loaded: it starts a model and names no gate. None when it may load (#998)."""
    text = plistlib.dumps(plist).decode("utf-8", errors="replace")
    if not MODEL_START.search(text) or GATE_WORDS.search(text):
        return None
    return f"Not loaded: {label} starts a model and names no gate. {gate_fix(text, False, label)}"


def refreshes(tasks_dir: Path | None = None, agents_dir: Path | None = None, home: Path | None = None,
              prefixes=None, found=None) -> list[tuple[str, bool]]:
    """Each job that refreshes a dashboard or page, as (name, starts_a_claude_session). A scheduled task always runs in
    a Claude session. A launchd job does when its command line runs the claude program."""
    home = home or Path.home()
    prefixes = tuple(prefixes if prefixes is not None else label_prefixes())
    tasks_dir = tasks_dir or home / ".claude" / "scheduled-tasks"
    agents_dir = agents_dir or home / "Library" / "LaunchAgents"
    out = []
    for name, text, _ in (found if found is not None else jobs(tasks_dir, agents_dir, home, prefixes)):
        if not (REFRESH_WORDS.search(name + " " + text) and PAGE_WORDS.search(text)):
            continue
        is_task = (tasks_dir / name / "SKILL.md").is_file()
        out.append((name, is_task or bool(re.search(r"(^|[/<>\s])claude(\s|<|$)", text))))
    return out


def check(tasks_dir: Path | None = None, agents_dir: Path | None = None, runs=None, retired=None,
          prefixes=None, repo_root: Path | None = None, home: Path | None = None, archived=None, crons=None) -> list[Finding]:
    """Findings for every scheduled task and launchd job. `runs` is a dict of task to Run lists, a callable returning one, or None to read the app's files. `crons` is a dict of task to (cron, enabled), or None to read the app's file."""
    home = home or Path.home()
    tasks_dir = tasks_dir or home / ".claude" / "scheduled-tasks"
    agents_dir = agents_dir or home / "Library" / "LaunchAgents"
    retired = tuple(retired if retired is not None else retired_names())
    prefixes = tuple(prefixes if prefixes is not None else label_prefixes())
    if repo_root is None:
        from lib import placement
        repo_root = placement.config().root
    archived = archived or repo_state.archived
    out: list[Finding] = []
    tracked: dict[Path, tuple[Path, set[str]]] = {}
    repo_seen: dict[str, str | None] = {}
    listed = jobs(tasks_dir, agents_dir, home, prefixes)
    for name, text, paths in listed:
        lowered = text.lower()
        for word in retired:
            if word.lower() in lowered:
                out.append(Finding("FAIL", name, f"names the retired {word}"))
        for raw in paths:
            path = Path(raw)
            if not path.exists():
                if not _is_output(path):
                    out.append(Finding("FAIL", name, f"{raw} does not exist"))
                continue
            try:
                inside = path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                inside = None
            if inside is not None and inside.parts:
                repo = inside.parts[0]
                if repo not in repo_seen:
                    repo_seen[repo] = archived(repo_root / repo) if (repo_root / repo / ".git").exists() else None
                if repo_seen[repo]:
                    out.append(Finding("FAIL", name, f"{raw} is in {repo}, which is {repo_seen[repo]} on GitHub"))
                    continue
            if path.is_file() and path.suffix in SCRIPT_SUFFIXES:
                root = _git_root(path.resolve())
                if root is None:
                    continue
                if root not in tracked:
                    tracked[root] = (root.resolve(), set(gitfiles.tracked_files(root)))
                resolved_root, files = tracked[root]
                if str(path.resolve().relative_to(resolved_root)) not in files:
                    out.append(Finding("WARN", name, f"{raw} is not tracked by git in {root.name}"))
    for name, spends in refreshes(tasks_dir, agents_dir, home, prefixes, found=listed):
        if spends:
            out.append(Finding("WARN", name, f"refreshes a page but starts a Claude session on every run. {TOKEN_FREE_HINT}"))
    for name, per_day in ungated(tasks_dir, crons if crons is not None else task_crons()):
        rate = "an unknown number of times" if per_day is None else f"{round(per_day, 2):g} time{'s' if per_day != 1 else ''}"
        out.append(Finding("FAIL", name, f"runs a model {rate} a day and names no gate command. {gate_fix('', True, name)}"))
    for name, text, _ in listed:
        if (tasks_dir / name / "SKILL.md").is_file() or not re.search(r"(^|[/<>\s])claude(\s|<|$)", text) or GATE_WORDS.search(text):
            continue
        rate = _launchd_rate(text)
        out.append(Finding("FAIL", name, f"is a launchd job that starts a Claude session {rate} a day and names no gate command. {gate_fix(text, False, name)}"))
    history = runs() if callable(runs) else runs if runs is not None else task_runs()
    for task, lst in sorted((history or {}).items()):
        last = lst[-LAST_RUNS:]
        if len(last) == LAST_RUNS and all(r.state != "ok" for r in last):
            out.append(Finding("WARN", task, f"its last {LAST_RUNS} runs ended {', '.join(r.state for r in last)}"))
    return out


def summary(tasks_dir: Path | None = None, agents_dir: Path | None = None, home: Path | None = None) -> int:
    """How many tasks and jobs `check` reads, for the OK line."""
    home = home or Path.home()
    return len(jobs(tasks_dir or home / ".claude" / "scheduled-tasks", agents_dir or home / "Library" / "LaunchAgents", home, label_prefixes()))


if __name__ == "__main__":
    for f in check():
        print(f"[{f.level}] {f.task}: {f.text}")
    for job, spends in refreshes():
        print(f"[REFRESH] {job}: {'starts a Claude session' if spends else 'no model call'}")
