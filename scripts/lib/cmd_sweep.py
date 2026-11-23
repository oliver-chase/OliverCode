"""Launcher command `board sweep`: the nightly board sweep, shell and python3 and gh only, with no model call (#641).

`olivercode board sweep` runs `skills/backlog/scripts/check_board_hygiene.py --dimension drift` against the board of
OliverCode and of every cloned fleet repo that has a `docs/backlog-config.json`, counts the cards that drifted (a closed
issue whose card is not Complete, a card whose Status disagrees) and the open issues with no card, and writes one line per
board into the owner queue (`olivercode owner`). A board with drift or a missing card also sends one alert. A board it could
not read, because the GraphQL budget is under the shared floor or a call failed, gets a line that says the sweep did not run
and is never reported clean. The board read goes through the shared local copy (`board_mirror.py`), so a sweep right after
another reader spends no GraphQL points. `--schedule` installs a launchd job that runs it at 02:30, `--unschedule` removes it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from lib import cmd_burndown, cmd_owner, gh_budget, launchd
from lib.local_config import OC_ROOT, backlog_config
from lib.repo_profiles import iter_fleet, load_repo_profiles

LABEL = "com.olivercode.sweep"
SESSION = "nightly-sweep"
USAGE = "Usage: olivercode board sweep [--schedule | --unschedule]"
HYGIENE = OC_ROOT / "skills" / "backlog" / "scripts" / "check_board_hygiene.py"
MISSING = "open issue not on the board"


def _verify(config: Path) -> None:
    """Exit when the config holds placeholders or names a repo that is not its checkout's origin."""
    sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
    import check_board_hygiene  # noqa: PLC0415
    check_board_hygiene.verify_config(json.loads(config.read_text(encoding="utf-8")), config)


def boards() -> list[tuple[str, Path]]:
    """(name, backlog config) for OliverCode and every cloned fleet repo whose board has a config, one per Project."""
    repos = [("OliverCode", OC_ROOT)]
    try:
        profiles, _ = load_repo_profiles(OC_ROOT)
        repos += [(name, path) for name, _, path in iter_fleet(profiles, OC_ROOT.parent) if (path / ".git").exists()]
    except (OSError, ValueError):
        pass
    found, seen = [], set()
    for name, path in repos:
        config = path / "docs" / "backlog-config.json"
        try:
            key = tuple(backlog_config(path)[k] for k in ("projectOwner", "projectNumber"))
            _verify(config)
        except (OSError, ValueError, KeyError, SystemExit):  # a config that names another repo's Project is never swept (#687)
            continue
        if key not in seen:
            seen.add(key)
            found.append((name, config))
    return found


def hygiene(config: Path, *dimensions: str, no_cache: bool = False) -> tuple[int, str]:
    """(exit code, output) of check_board_hygiene.py for the given dimensions."""
    cmd = [sys.executable, str(HYGIENE), "--config", str(config)]
    for d in dimensions:
        cmd += ["--dimension", d]
    if no_cache:
        cmd.append("--no-cache")
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, f"check_board_hygiene.py: {exc}"
    return done.returncode, (done.stdout + done.stderr).strip()


def counts(output: str) -> tuple[int, int] | None:
    """(drifted cards, missing cards) from a drift sweep's output, or None when the sweep did not finish."""
    if "status-drift: clean." in output:
        return 0, 0
    lines = [l for l in output.splitlines() if l.strip().startswith("- [status-drift]")]
    if not lines or not re.search(r"\d+ finding\(s\)", output):
        return None
    missing = sum(MISSING in l for l in lines)
    return len(lines) - missing, missing


def line(name: str, found: tuple[int, int] | None, reason: str = "") -> str:
    if found is None:
        return f"{name}: the sweep did not run ({reason or 'the board could not be read'}), so the state of the board is unknown"
    drift, missing = found
    return f"{name}: {drift} drifted card(s), {missing} missing card(s)" + ("" if drift or missing else ", clean")


def _ran_file() -> Path:
    from lib import failure_log
    return failure_log.home() / "sweep-state.json"


def stamp_ran(now: float | None = None) -> None:
    """Record when a sweep last finished, for `olivercode health` (#726). A write error never fails the sweep."""
    try:
        _ran_file().parent.mkdir(parents=True, exist_ok=True)
        _ran_file().write_text(json.dumps({"ok": time.time() if now is None else now}), encoding="utf-8")
    except OSError:
        pass


def last_ran() -> float | None:
    try:
        return float(json.loads(_ran_file().read_text(encoding="utf-8"))["ok"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def run(board_list=boards, check=hygiene, push=None, refusal=None, out=print) -> int:
    """Sweep every board, queue one line per board, alert once on any drift. Returns 1 when any board has a finding."""
    push = push or (lambda text: cmd_burndown.notify(text, "OliverCode board sweep"))
    held = (refusal or (lambda: gh_budget.refusal() or gh_budget.points_refusal()))()
    flagged = []
    for name, config in board_list():
        if held:
            text, bad = line(name, None, held.split(". ")[0]), True
        else:
            code, output = check(config, "drift")
            found = counts(output)
            text, bad = line(name, found, output.splitlines()[-1][:120] if output else ""), found != (0, 0)
        out(text)
        cmd_owner.note(SESSION, text)
        if bad:
            flagged.append(text)
    if flagged:
        push("Board sweep: " + "; ".join(flagged))
    if not held:
        stamp_ran()
    return 1 if flagged else 0


def repos(board_list=boards) -> list[tuple[str, str, int]]:
    """(name, owner/repo, epic number) for each board, for the intake check. The epic is the Epic line the repo's stories carry."""
    out = []
    for name, config in board_list():
        try:
            cfg = json.loads(config.read_text(encoding="utf-8"))
            out.append((name, f"{cfg['repoOwner']}/{cfg['repoName']}", int(cfg.get("epic") or 1)))
        except (OSError, ValueError, KeyError):
            continue
    return out


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["board", "sweep"], "sweep.out", StartCalendarInterval={"Hour": 2, "Minute": 30}), "board sweep job",
                            "`olivercode board sweep` runs daily at 02:30. Remove it with `olivercode board sweep --unschedule`.")


def command_sweep(argv: list[str]) -> int:
    if argv in (["--schedule"], ["--unschedule"]):
        return schedule(argv == ["--schedule"])
    if argv:
        print(USAGE)
        return 1
    from lib import intake
    held = gh_budget.refusal() or gh_budget.points_refusal()
    code = run()
    if held:
        print("Intake check skipped: " + held.split(". ")[0])
        return code
    fleet = repos()
    for line in intake.prevention(*fleet[0][1:]) if fleet else []:
        print(line)
    return max(code, intake.run(fleet))
