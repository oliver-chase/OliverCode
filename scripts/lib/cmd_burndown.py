"""Launcher command `board burndown`: open issue counts per fleet repo and the change since the last run, from gh only, with no model call.

`olivercode board burndown` prints one line per repo, appends the run to ~/.olivercode/burndown.log and sends one ntfy line (or a desktop notification without a topic) only when a count changed.
`--schedule` installs a launchd job that runs it every 15 minutes, and `--unschedule` removes it. A repo GitHub archived or deleted is left out, and a
GitHub hold or a failed read skips that repo for the run.

Each run also prints the day's numbers: open stories across the repos read. Tokens per closed story and
threads typed into have no per-day record yet, so the line says they are not recorded by day.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from lib import failure_log, gh_budget, launchd, repo_state
from lib.local_config import OC_ROOT
from lib.repo_profiles import iter_fleet, load_repo_profiles

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import issue_count  # noqa: E402

LABEL = "com.olivercode.burndown"
INTERVAL = 900
USAGE = "Usage: olivercode board burndown [--schedule | --unschedule]"
NOT_RECORDED = "not recorded by day"


def slugs() -> list[str]:
    """owner/name for OliverCode and every cloned, active fleet repo."""
    found = [repo_state.origin(OC_ROOT)]
    try:
        profiles, _ = load_repo_profiles(OC_ROOT)
        found += [repo_state.origin(path) for _, _, path in iter_fleet(profiles, OC_ROOT.parent) if (path / ".git").exists()]
    except (OSError, ValueError):
        pass
    return list(dict.fromkeys(s for s in found if s))


def fetch(slug: str) -> int | None:
    """Open issue count from the issues list API (a search count lags), or None when GitHub holds the budget or the call fails."""
    if gh_budget.refusal():
        return None
    return issue_count.count_issues(slug, "open")


def notify(text: str, title: str = "OliverCode burn-down") -> None:
    """One line to ntfy when OLIVERCODE_NTFY_TOPIC is set, otherwise a desktop notification."""
    topic = os.environ.get("OLIVERCODE_NTFY_TOPIC")
    if topic:
        subprocess.run(["curl", "-s", "-H", f"Title: {title}", "-d", text, f"https://ntfy.sh/{topic}"], capture_output=True, timeout=20)
    else:
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title {json.dumps(title)}'], capture_output=True, timeout=20)


def daily_line(day: str, open_total: int, repos_read: int) -> str:
    """The day's numbers in one line: open stories across the repos read and the two numbers with no per-day record."""
    return (f"{day}: {open_total} open stories across {repos_read} repos, "
            f"tokens per closed story {NOT_RECORDED}, threads typed into {NOT_RECORDED}")


def run(repos=slugs, count=fetch, push=notify, clock=time.time, out=print) -> int:
    state_file = failure_log.home() / "burndown.json"
    try:
        before = json.loads(state_file.read_text(encoding="utf-8")).get("counts", {})
    except (OSError, ValueError):
        before = {}
    now, counts, lines, changed, read = clock(), dict(before), [], [], []
    for slug in repos():
        n = count(slug)
        if n is None:
            lines.append(f"{slug}: not read")
            continue
        counts[slug] = n
        read.append(n)
        delta = n - before[slug] if slug in before else None
        if delta:
            changed.append(f"{slug.split('/')[-1]} {n} ({delta:+d})")
        lines.append(f"{slug}: {n} open" + (f" ({delta:+d} since the last run)" if delta else ""))
    failure_log.home().mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"counts": counts, "t": now}), encoding="utf-8")
    log = failure_log.home() / "burndown.log"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M ", time.localtime(now)) + "; ".join(lines) + "\n")
    failure_log.trim(log)
    for line in lines:
        out(line)
    out(daily_line(time.strftime("%Y-%m-%d", time.localtime(now)), sum(read), len(read)))
    if changed:
        push("Open issues changed: " + "; ".join(changed))
    return 0


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["board", "burndown"], "burndown.out", StartInterval=INTERVAL), "burn-down job",
                            "`olivercode board burndown` runs every 15 minutes. Remove it with `olivercode board burndown --unschedule`.")


def command_burndown(argv: list[str]) -> int:
    if argv == ["--schedule"] or argv == ["--unschedule"]:
        return schedule(argv == ["--schedule"])
    if argv:
        print(USAGE)
        return 1
    return run()
