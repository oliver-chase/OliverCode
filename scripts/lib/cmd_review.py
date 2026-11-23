"""Launcher command `review`: the recurring review, configured in the private fleet repo (#821).

`olivercode review [--schedule | --unschedule]` reads `review-config.json` from the folder of the fleet registry, then runs
the steps it switches on: `conform`, `boardSweep`, `updateCheck` (reports how far this checkout trails its upstream) and
`alwaysUpToDate` (runs `olivercode update`). `schedule` holds the cadence the launchd job uses. The engine holds no settings.
"""

from __future__ import annotations

import json
import subprocess
import sys

from lib import launchd
from lib.local_config import OC_ROOT, fleet_registry_path

TEMPLATE = OC_ROOT / "core" / "templates" / "fleet"
LABEL = "com.olivercode.review"
USAGE = "Usage: olivercode review [--schedule | --unschedule]"
LAUNCHER = [sys.executable, str(OC_ROOT / "scripts" / "olivercode")]
STEPS = (("conform", "conform"), ("boardSweep", "board sync"), ("alwaysUpToDate", "update"))
DAYS = {"weekly": {"Weekday": 1}, "daily": {}}


def config_path():
    return fleet_registry_path().parent / "review-config.json"


def review_config() -> dict:
    path = config_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def update_check(runner) -> int:
    runner(["git", "-C", str(OC_ROOT), "fetch", "--quiet"], capture_output=True, text=True)
    out = runner(["git", "-C", str(OC_ROOT), "rev-list", "--count", "HEAD..@{u}"], capture_output=True, text=True)
    behind = (out.stdout or "0").strip()
    print(f"update-check: this checkout is {behind} commit(s) behind its upstream." + (" Run `olivercode update`." if behind not in ("0", "") else ""))
    return 0


def schedule(on: bool, cadence: dict) -> int:
    when = {"Hour": int(cadence.get("hour", 9)), "Minute": 0, **DAYS.get(cadence.get("cadence", "weekly"), DAYS["weekly"])}
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["review"], "review.out", StartCalendarInterval=when), "recurring review job",
                            f"`olivercode review` runs {cadence.get('cadence', 'weekly')}. Remove it with `olivercode review --unschedule`.")


def command_review(argv: list[str], runner=subprocess.run) -> int:
    if argv not in ([], ["--schedule"], ["--unschedule"]):
        print(USAGE)
        return 1
    config = review_config()
    if not config:
        print(f"No review config at {config_path()}. Run `olivercode init-fleet` to create the fleet repo that holds it.")
        return 1
    if argv:
        return schedule(argv == ["--schedule"], config.get("schedule", {}))
    failed = []
    if config.get("updateCheck"):
        update_check(runner)
    for key, command in STEPS:
        if config.get(key):
            code = runner([*LAUNCHER, *command.split()]).returncode
            print(f"{command}: {'done' if not code else 'failed, see the output above'}")
            if code:
                failed.append(command)
    print("review: " + (f"{', '.join(failed)} failed." if failed else "every enabled step ran."))
    return 1 if failed else 0
