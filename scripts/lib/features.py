"""`olivercode features --repo NAME`: the feature register in docs/STANDARDS.json read against one repo.

Each row names a feature, the command that shows its state, the command that turns it on and whether only the owner can.
The `id` of a row selects its test in TESTS. `conform` reads the same rows, so a repo with a feature off fails the gate
and the failure names each enable command (#723, #727).
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from lib import failure_log, local_config
from lib.local_config import OC_ROOT

REGISTER = OC_ROOT / "docs" / "STANDARDS.json"
USAGE = "Usage: olivercode features --repo NAME|DIR [--enable [--commit --story REF]] | --explain | --retire NAME --reason TEXT"
FIELDS = ("id", "title", "check", "enable", "owner_only", "freshness", "explain")
MACHINES = ("each", "single")  # every machine must have the feature, or one machine keeps an owner view and the row says why (#740)
FRESHNESS = ("last-run", "exists")  # a job row is on only when its last run exited 0 and is newer than twice its interval (#748)


@dataclass
class Feature:
    id: str
    title: str
    check: str
    enable: str
    owner_only: bool
    freshness: str = "exists"
    machine: str = "each"
    single_reason: str = ""
    explain: str = ""
    on: bool = False
    retired: str = ""
    state: str = "off"  # on, off, failing or stale
    note: str = ""


def load(path: Path | None = None) -> list[dict]:
    """The register's rows."""
    return json.loads((path or REGISTER).read_text(encoding="utf-8"))["features"]


def _config(repo: Path) -> dict:
    try:
        return local_config.backlog_config(repo)
    except (OSError, ValueError):
        return {}


def _oc_home(home: Path | None) -> Path:
    return home / ".olivercode" if home else failure_log.home()


def _agent(home: Path | None, label: str) -> bool:
    return ((home or Path.home()) / "Library" / "LaunchAgents" / f"{label}.plist").is_file()


def _has_hooks(repo: Path, home: Path | None) -> bool:
    from lib import conform
    return conform.hooks(repo, oc_root=OC_ROOT).status == "pass"


def _file(name: str):
    return lambda repo, home: (_oc_home(home) / name).is_file()


def _missing_hooks(home: Path | None) -> list[str]:
    from lib import claude_settings
    return claude_settings.missing((home or Path.home()) / ".claude" / "settings.json")


def _job(*labels: str):
    return lambda repo, home: any(_agent(home, label) for label in labels)


def launchctl_exit(label: str) -> int | None:
    """The last exit status launchd holds for LABEL, or None when it is not loaded or has not run."""
    ran = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True)
    found = re.search(r"last exit code = (\d+)", ran.stdout) if ran.returncode == 0 else None
    return int(found.group(1)) if found else None


EXIT = launchctl_exit  # a fixture replaces it; a run with a fixture home never asks launchd


def _interval(plist: dict) -> int:
    if plist.get("StartInterval"):
        return int(plist["StartInterval"])
    return 7 * 86400 if "Weekday" in (plist.get("StartCalendarInterval") or {}) else 86400


GH_MISSING = "No such file or directory: 'gh'"


def _plist_path_has_gh(plist: dict) -> bool:
    """True when the job's own PATH holds a folder with gh, as launchd.schedule writes it since #799."""
    folders = (plist.get("EnvironmentVariables") or {}).get("PATH", "").split(os.pathsep)
    return any((Path(f) / "gh").is_file() for f in folders if f)


def last_run(label: str, home: Path | None, now: float | None = None) -> tuple[str, str]:
    """The state of the job LABEL: ("on", ""), ("failing", ERROR LINE) or ("stale", AGE). Its log, or its plist while it has not logged, dates the last run."""
    plist_path = (home or Path.home()) / "Library" / "LaunchAgents" / f"{label}.plist"
    try:
        plist = plistlib.loads(plist_path.read_bytes())
    except (OSError, ValueError):
        plist = {}
    log = Path(plist.get("StandardOutPath", "")) if plist.get("StandardOutPath") else None
    code = EXIT(label) if home is None or EXIT is not launchctl_exit else None
    if code:
        lines = []
        try:
            lines = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()] if log else []
        except OSError:
            pass
        last = lines[-1] if lines else ""
        if GH_MISSING in last and _plist_path_has_gh(plist):  # the job now carries gh on its PATH (#799), so the logged miss is history
            return "on", ""
        return "failing", last or f"exited {code} with no output"
    if log and log.is_file() and log.stat().st_size == 0:  # launchd creates the log when the job first runs, and a clean silent run never rewrites it (#842)
        return "on", ""
    ran = next((p.stat().st_mtime for p in (log, plist_path) if p and p.is_file()), 0)
    age, limit = (now or time.time()) - ran, 2 * _interval(plist)
    return ("stale", f"last ran {int(age // 3600)} hours ago, over twice its interval") if age > limit else ("on", "")


TESTS = {
    "board-baseline": lambda repo, home: {"status", "priority", "size"} <= set(_config(repo).get("fields", {})),
    "story-template": lambda repo, home: bool(_config(repo).get("repoName")),
    "area-label": lambda repo, home: "area" in _config(repo).get("fields", {}),
    "hooks": _has_hooks,
    "permission-policy": lambda repo, home: (repo / ".olivercode" / "policy.json").is_file(),
    "owner-queue": _file("owner-queue.jsonl"),
    "burndown": _job("com.olivercode.burndown"),
    "decision-records": _file("relays.jsonl"),
    "lessons-retro": _job("com.olivercode.lessons"),
    "nightly-sweep": _job("com.olivercode.sweep"),
    "groom-schedule": _job("com.olivercode.groom", "com.olivercode.maintain"),
    "maintain-job": _job("com.olivercode.maintain"),
    "headless-builders": lambda repo, home: shutil.which("claude") is not None,
    "worktree-cleanup": _job("com.olivercode.maintain"),
    "unfinished-work-snapshot": lambda repo, home: "wip_save.py" not in _missing_hooks(home),
    "gap-sweep": _job("com.olivercode.gap-sweep"),
    "fleet-sync": _job("com.olivercode.fleet-sync"),
    "review": _job("com.olivercode.review"),
    "gh-replay": _job("com.olivercode.gh-replay"),
    "version-cut": _job("com.olivercode.version-cut"),
    "board-sweep": _job("com.olivercode.board-sweep"),
}


def _retired_path(home: Path | None) -> Path:
    return _oc_home(home) / "retired-features.json"


def retired(home: Path | None = None) -> dict[str, str]:
    """The retired feature ids with the reason the owner gave (#747)."""
    try:
        data = json.loads(_retired_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _remove_agent(home: Path | None, label: str) -> None:
    if home is None:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
    (((home or Path.home()) / "Library" / "LaunchAgents") / f"{label}.plist").unlink(missing_ok=True)


def _generated(home: Path | None, repo: Path | None) -> dict:
    """What each row generates: the job labels and files its retirement removes."""
    h = _oc_home(home)
    return {"owner-queue": (h / "owner-queue.jsonl",), "usage-profile": (h / "usage-profile.json",),
            "permission-policy": ((repo / ".olivercode" / "policy.json",) if repo else ()),
            "groom-schedule": ("com.olivercode.groom",)} | {k: v for k, v in JOBS.items() if k not in ("groom-schedule", "worktree-cleanup")}


def retire(name: str, reason: str, home: Path | None = None, rows: list[dict] | None = None, repo: Path | None = None,
           record=None) -> list[str]:
    """Retire feature NAME: turn its jobs off, remove its generated files, mark it retired and write the reason as a decision record.

    Returns what was removed. An unknown NAME or an empty REASON raises ValueError. The decision-records row keeps the log
    the record goes into, so retiring it removes nothing.
    """
    ids = [r["id"] for r in (rows if rows is not None else load())]
    if name not in ids:
        raise ValueError(f"{name} is not a feature in the register ({', '.join(ids)})")
    if not reason.strip():
        raise ValueError("--reason TEXT is required: the record keeps why the feature was retired")
    removed = []
    for item in _generated(home, repo).get(name, ()):
        if isinstance(item, Path):
            if item.is_file():
                item.unlink()
                removed.append(str(item))
        else:
            _remove_agent(home, item)
            removed.append(item)
    state = retired(home) | {name: reason.strip()}
    path = _retired_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if record is None:
        from lib import relay
        record = relay.record
    record(reason.strip(), f"retire-{name}", ["retire", "keep"], "features", "retire", "owner")
    return removed


JOBS = {"burndown": ("com.olivercode.burndown",), "lessons-retro": ("com.olivercode.lessons",), "nightly-sweep": ("com.olivercode.sweep",),
        "groom-schedule": ("com.olivercode.groom", "com.olivercode.maintain"), "maintain-job": ("com.olivercode.maintain",),
        "worktree-cleanup": ("com.olivercode.maintain",),
        "gap-sweep": ("com.olivercode.gap-sweep",), "fleet-sync": ("com.olivercode.fleet-sync",),
        "gh-replay": ("com.olivercode.gh-replay",), "version-cut": ("com.olivercode.version-cut",), "board-sweep": ("com.olivercode.board-sweep",), "review": ("com.olivercode.review",)}


def _state(row_id: str, freshness: str, repo: Path, home: Path | None) -> tuple[str, str]:
    if not TESTS[row_id](repo, home):
        return "off", ""
    if freshness == "last-run" and row_id in JOBS:
        label = next(l for l in JOBS[row_id] if _agent(home, l))
        return last_run(label, home)
    return "on", ""


def evaluate(repo: Path, home: Path | None = None, rows: list[dict] | None = None) -> list[Feature]:
    """Every register row with its state for REPO. A row with no test, or no check or enable command, is a register error."""
    found = []
    gone = retired(home)
    for row in rows if rows is not None else load():
        missing = [f for f in FIELDS if f not in row or row[f] in ("", None)]
        if missing or row["id"] not in TESTS:
            raise ValueError(f"register row {row.get('id', '?')} lacks {', '.join(missing) or 'a test in features.TESTS'}")
        if row["freshness"] not in FRESHNESS:
            raise ValueError(f"register row {row['id']} names freshness {row['freshness']!r}, which is not one of {', '.join(FRESHNESS)}")
        if row.get("machine", "each") not in MACHINES:
            raise ValueError(f"register row {row['id']} names machine {row['machine']!r}, which is not one of {', '.join(MACHINES)}")
        if row.get("machine") == "single" and not str(row.get("single_reason", "")).strip():
            raise ValueError(f"register row {row['id']} is single-machine and gives no single_reason")
        feature = Feature(**{f: row[f] for f in FIELDS}, machine=row.get("machine", "each"), single_reason=row.get("single_reason", ""))
        feature.retired = gone.get(row["id"], "")
        feature.state, feature.note = ("retired", "") if feature.retired else _state(row["id"], feature.freshness, repo, home)
        feature.on = feature.state == "on"
        found.append(feature)
    return found


# Each scheduled job's label suffix, then what it does and when it runs (#744). A test fails on a job label in scripts/ with no line here.
JOB_GUIDE = {
    "sweep": "The nightly board sweep at 02:30 finds cards out of step with their issues and writes one line per board to your owner queue.",
    "gap-sweep": "The gap sweep runs nightly and files one story for each standard a repo has off, at most five per repo.",
    "groom": "Groom runs from the daily maintenance job and sets Priority and Size, moves ready stories forward and flags duplicates.",
    "burndown": "Burndown counts open issues per repo every 15 minutes and alerts you only when a count changes.",
    "fleet-sync": "Fleet sync runs at 03:30 and brings every clean fleet repo level with GitHub, leaving any conflict in your owner queue.",
    "review": "The recurring review runs on the schedule in your fleet repo and does the conform, board sync, update-check and update steps that repo switches on.",
    "maintain": "Maintain runs daily and repairs what is safe, such as broken links, merged branches and empty worktrees, and reports the rest.",
    "gh-replay": "GitHub replay runs every ten minutes and sends the commands queued during a GraphQL limit once the limit resets.",
    "lessons": "The lessons job runs the weekly retro, which adds a candidate for each lesson with no check.",
    "board-sweep": "The board sweep runs every thirty minutes, moves the card of each closed issue to Complete and adds each open issue that has no card.",
    "version-cut": "Version cut reads the day's commits on main, picks the version and writes that day's changelog section.",
}


def explain(repo: Path, home: Path | None = None, rows: list[dict] | None = None) -> str:
    """The plain guide: one sentence per feature in the register, then one per scheduled job with whether it is loaded on this machine."""
    lines = ["Features: what each is, where it lives and how to open it"]
    lines += [f"  {f.title}: {f.explain}" for f in evaluate(repo, home, rows)]
    lines.append("Scheduled jobs: what each does, when it runs and whether it is loaded on this machine")
    for name, text in JOB_GUIDE.items():
        lines.append(f"  [{'LOADED' if _agent(home, 'com.olivercode.' + name) else 'NOT LOADED'}] {text}")
    return "\n".join(lines)


def command_for(feature: Feature, repo: Path) -> str:
    return feature.enable.replace("{repo}", str(repo))


def off(repo: Path, home: Path | None = None, rows: list[dict] | None = None) -> list[Feature]:
    """The off rows the owner does not have to turn on, each one a gap an agent closes."""
    return [f for f in evaluate(repo, home, rows) if not f.on and not f.owner_only and not f.retired]


def runnable(command: str) -> bool:
    """False when the enable command still holds an all-caps placeholder (TEXT, ID, NAME) the agent has no value for."""
    return not any(re.fullmatch(r"[A-Z]{2,}", tok) for tok in command.split())


def enable(repo: Path, home: Path | None = None, rows: list[dict] | None = None, run=subprocess.run, out=print) -> list[str]:
    """Run the enable command of every off feature an agent can turn on, once per distinct command (#726).

    Returns the commands that failed or needed a value the agent does not have; each is a gap for a story."""
    left = []
    for command in dict.fromkeys(command_for(f, repo) for f in off(repo, home, rows)):
        if not runnable(command):
            out(f"Skipped, it needs a value: {command}")
            left.append(command)
            continue
        argv = shlex.split(command)
        argv = [sys.executable, str(OC_ROOT / "scripts" / "olivercode"), *argv[1:]] if argv[0] == "olivercode" else argv
        done = run(argv, capture_output=True, text=True, timeout=300)
        out(f"{'Ran' if done.returncode == 0 else 'Failed'}: {command}")
        if done.returncode:
            left.append(command)
    return left


def _resolve(name: str) -> Path | None:
    path = Path(name).expanduser()
    if path.is_dir():
        return path.resolve()
    from lib.repo_profiles import iter_fleet, load_repo_profiles
    if name.lower() == "olivercode":
        return OC_ROOT
    profiles, _ = load_repo_profiles(OC_ROOT)
    return next((p for n, _, p in iter_fleet(profiles, OC_ROOT.parent, skip_archived=False) if n.lower() == name.lower()), None)


def command_features(argv: list[str], out=print, home: Path | None = None) -> int:
    if argv[:1] == ["--retire"]:
        if len(argv) != 4 or argv[2] != "--reason":
            out(USAGE)
            return 1
        try:
            removed = retire(argv[1], argv[3], repo=OC_ROOT)
        except (OSError, ValueError) as err:
            out(f"Error: {err}")
            return 1
        out(f"Retired {argv[1]}. Removed: {', '.join(removed) or 'nothing to remove'}. The reason is recorded as decision retire-{argv[1]}.")
        return 0
    if argv == ["--explain"]:
        try:
            out(explain(OC_ROOT))
        except ValueError as err:
            out(f"Error: {err}")
            return 1
        return 0
    commit = "--commit" in argv
    argv = [a for a in argv if a != "--commit"]
    story = None
    if "--story" in argv and argv.index("--story") + 1 < len(argv):
        at = argv.index("--story")
        story, argv = argv[at + 1], argv[:at] + argv[at + 2:]
    turn_on = len(argv) == 3 and argv[2] == "--enable"
    if (len(argv) != 2 and not turn_on) or argv[0] != "--repo" or (commit and not (turn_on and story)):
        out(USAGE)
        return 1
    repo = _resolve(argv[1])
    if repo is None or not repo.is_dir():
        out(f"Error: {argv[1]} is not a fleet repo or a directory.")
        return 1
    try:
        if turn_on and commit:
            from lib.gitfiles import commit_after
            out(f"  [COMMIT] {repo.name}: " + commit_after(repo, lambda: enable(repo, home, out=out), f"Turn on the repo's standard features ({story})",
                                                            "Each feature the register lists as off now has its files in the repo."))
        elif turn_on:
            enable(repo, home, out=out)
        features = evaluate(repo, home)
    except (OSError, ValueError, subprocess.SubprocessError) as err:
        out(f"Error: {err}")
        return 1
    out(f"Features for {repo.name}")
    for f in features:
        if f.retired:
            out(f"  [RETIRED] {f.title}: {f.retired}")
            continue
        if f.state in ("failing", "stale"):
            out(f"  [{f.state.upper()}] {f.title}: {f.note}")
            out(f"         Fix: {command_for(f, repo)}")
            continue
        out(f"  [{'ON ' if f.on else 'OFF'}] {f.title}" + ("" if f.on else f"{' (owner only)' if f.owner_only else ''}"))
        if not f.on:
            out(f"         Enable: {command_for(f, repo)}")
    gaps = [f for f in features if not f.on and not f.owner_only and not f.retired]
    out(f"{len(gaps)} feature(s) off that an agent turns on, {sum(not f.on and f.owner_only and not f.retired for f in features)} owner only, "
        f"{sum(bool(f.retired) for f in features)} retired")
    return 1 if gaps else 0
