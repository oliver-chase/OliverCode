"""The launchd job that replays queued gh commands at the GraphQL reset (#669).

`olivercode gh-limit --schedule` installs a job that runs `olivercode gh-limit replay` every ten minutes. While GraphQL is
held the replay does nothing, and after the reset it writes each queued command and saves what it wrote in
~/.olivercode/gh-queue-report.txt. Then it flushes the story outbox (#1025), so queued stories file without a manual flush. The
job starts no Claude session.
"""

from __future__ import annotations

import sys

from lib import failure_log, gh_budget, launchd, story_outbox
from lib.cli import newer_python
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.gh-replay"


def run(story_runner=None) -> str:
    """One replay run: the gh queue, then the story outbox. The outbox stops at a hold or the hourly write cap, so over the cap
    nothing is sent and the requests wait for the next run. The report names each issue number filed."""
    lines = [gh_budget.replay()]
    try:
        filed, left, why = story_outbox.flush(story_runner) if story_runner else story_outbox.flush()
    except Exception as exc:  # noqa: BLE001 -- a missing gh must not hide the gh queue report above
        return "\n".join(lines + [f"Story outbox failed: {exc}"])
    lines += [f"Filed {ref} in {item['repo']}: {item['title']}" for item, ref in filed]
    if left:
        lines.append(f"{len(left)} story request(s) wait. Stopped: {why}.")
    return "\n".join(lines)


def plist() -> dict:
    log = str(failure_log.home() / "gh-replay.out")
    return {"Label": LABEL, "ProgramArguments": [newer_python() or sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "gh-limit", "replay"],
            "StartInterval": 600, "StandardOutPath": log, "StandardErrorPath": log}


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, plist, "GitHub replay job",
                            "queued gh commands replay after the GraphQL reset. Remove it with `olivercode gh-limit --unschedule`.")
