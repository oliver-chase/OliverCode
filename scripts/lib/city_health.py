"""City v2, the Health section (#1360): the latest validation, the slowest tests, gate blocks, the checks on main, the installed version, how old each record is,
the newest lessons and refusals. Each figure is read from the file that records it, and one that is not recorded says so in one line."""

from __future__ import annotations

import html
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log

SLOWEST = 5
LESSONS = 3
REFUSALS = 5
REPO = Path(__file__).resolve().parents[2]


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def card(title: str, lines: list[str]) -> str:
    return f'<div class="card"><h3>{esc(title)}</h3>' + "".join(f'<p class="small">{esc(line)}</p>' for line in lines) + "</div>"


def clock(stamp) -> str:
    return f"{datetime.fromtimestamp(float(stamp), timezone.utc):%d %b %H:%M} UTC"


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def validation() -> str:
    rows = []
    for line in read_lines(failure_log.home() / "validate-runs.jsonl"):
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict) and "at" in found:
            rows.append(found)
    if not rows:
        return card("Latest validation", ["Not recorded, because validate-runs.jsonl holds no run."])
    last = max(rows, key=lambda r: r["at"])
    run, wait = float(last.get("run") or 0), float(last.get("wait") or 0)
    # shortcut: the run row records time and queue wait only, so a pass or fail is not shown, when the row gains a result
    return card("Latest validation", [f"Ran {clock(last['at'])}, took {run:.0f} seconds, waited {wait:.0f} seconds in the queue.", "The run log does not record whether it passed."])


def slowest() -> str:
    try:
        timings = json.loads((failure_log.home() / "validate-timings.json").read_text(encoding="utf-8"))
        top = sorted(((n, float(s)) for n, s in timings.items()), key=lambda kv: -kv[1])[:SLOWEST]
    except (OSError, ValueError, AttributeError, TypeError):
        return card("Slowest test files", ["Not recorded, because validate-timings.json could not be read."])
    return card("Slowest test files", [f"{name}: {secs:.1f} seconds" for name, secs in top] or ["No test file is timed."])


def blocks() -> str:
    counted = Counter(gate for _when, _repo, gate, _reason in failure_log.entries()).most_common(SLOWEST)
    return card("Gate blocks", [f"{gate}: {n}" for gate, n in counted] or ["No gate block is recorded."])


def checks(github: dict | None) -> str:
    runs = (github or {}).get("checks")
    if runs is None:
        return card("Checks on main", ["Not recorded, because no GitHub reading has been saved."])
    read = f" Read at {clock(github['read_at'])}." if github.get("read_at") else " Read time not recorded."
    failed = [r["name"] for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral")]
    if not runs:
        return card("Checks on main", ["No check is recorded on main." + read])
    if failed:
        return card("Checks on main", [f"Failing: {', '.join(str(n) for n in failed)}." + read])
    return card("Checks on main", [f"All {len(runs)} checks pass." + read])


def git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def version() -> str:
    installed, staging = git("rev-parse", "--short", "HEAD"), git("rev-parse", "--short", "origin/staging")
    if not installed or not staging:
        return card("Installed version", ["Not recorded, because the installed commit or staging could not be read."])
    behind = git("rev-list", "--count", "HEAD..origin/staging")
    state = "level with staging" if installed == staging else f"{behind} commits behind staging" if behind else "different from staging"
    return card("Installed version", [f"Installed {installed}, staging {staging}: {state}."])


def hooks() -> str:
    folder = failure_log.home() / "hook-fires"
    try:
        newest = max(p.stat().st_mtime for p in folder.iterdir())
    except (OSError, ValueError):
        return card("Hook firing", ["Hook firing is not recorded."])
    return card("Hook firing", [f"Hook firing is no longer recorded since {datetime.fromtimestamp(newest, timezone.utc):%d %b}."])


def lessons() -> str:
    found = []
    for path in sorted((failure_log.home() / "lessons").glob("*.jsonl")):
        for line in read_lines(path):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("what"):
                found.append(row)
    newest = sorted(found, key=lambda r: str(r.get("date") or ""), reverse=True)[:LESSONS]
    return card("Newest lessons", [f"{r.get('date') or 'date not recorded'}: {r['what']}" + (f" Rule: {r['rule']}" if r.get("rule") else "") for r in newest] or ["No lesson is recorded."])


def refusals() -> str:
    newest = sorted(failure_log.entries(), key=lambda row: row[0], reverse=True)[:REFUSALS]
    return card("Newest refusals", [f"{when}, {repo}: {gate} refused. {reason}" for when, repo, gate, reason in newest] or ["No refusal is recorded."])


def render(data: dict) -> str:
    """The Health section as HTML, from the page's figures in DATA."""
    cards = validation() + slowest() + blocks() + checks(data.get("github")) + version() + hooks() + lessons() + refusals()
    return ('<section class="chap" id="health" aria-labelledby="h0"><h2 id="h0">Health</h2>'
            '<style>#health .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:16px;align-items:start}</style>'
            f'<div class="grid2">{cards}</div></section>')
