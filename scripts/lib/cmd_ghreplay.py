"""The launchd job that replays queued gh commands at the GraphQL reset (#669).

`olivercode gh-limit --schedule` installs a job that runs `olivercode gh-limit replay` every ten minutes. While GraphQL is
held the replay does nothing, and after the reset it writes each queued command and saves what it wrote in
~/.olivercode/gh-queue-report.txt. The
job starts no Claude session.
"""

from __future__ import annotations

import sys

from lib import failure_log, gh_budget, launchd
from lib.cli import newer_python
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.gh-replay"


def run() -> str:
    """One replay run of the gh queue. With the queue empty the run returns '', so an idle job prints nothing to its log."""
    return gh_budget.replay() or ""


def plist() -> dict:
    log = str(failure_log.home() / "gh-replay.out")
    return {"Label": LABEL, "ProgramArguments": [newer_python() or sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "gh-limit", "replay"],
            "StartInterval": 600, "StandardOutPath": log, "StandardErrorPath": log}


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, plist, "GitHub replay job",
                            "queued gh commands replay after the GraphQL reset. Remove it with `olivercode gh-limit --unschedule`.")
