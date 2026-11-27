"""City v2, the Health section (#1360, mirrored from docs/city/Main.dc.html in #1385): a lead sentence, the checks on main, the test queue wait, the gate blocks,
the test runs and the slowest test files as the mockup's tiles and bars, then the lessons, refusals and record age as plain lines. Each figure is read from the
file that records it, and one that is not recorded says so in one line."""

from __future__ import annotations

import html
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log

SHOWN_GATES = 4
SHOWN_SLOWEST = 5
SHOWN_REFUSALS = 2
MAX_REFUSALS = 20
SHOWN_LESSONS = 3
MAX_LESSONS = 20
PASSING = ("success", "skipped", "neutral")
REPO = Path(__file__).resolve().parents[2]


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def clock(stamp) -> str:
    return f"{datetime.fromtimestamp(float(stamp), timezone.utc):%d %b %H:%M} UTC"


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def fold(rows: list[str], label: str, shown: int) -> str:
    """ROWS after the first SHOWN sit behind a See all control, which the page script opens and remembers across the 60-second reload (city.fold does the same for the owner queue)."""
    if len(rows) <= shown:
        return "".join(rows)
    return f'{"".join(rows[:shown])}<div class="fold" hidden>{"".join(rows[shown:])}</div><a class="more" href="#" data-fold="See all {len(rows)} {label}">See all {len(rows)} {label}</a>'


def card(title: str, body: str, style: str = "") -> str:
    return f'<div class="card"{style}><h3>{esc(title)}</h3>{body}</div>'


def tile(label: str, number: str, bench: str, mean: str, style: str = "") -> str:
    return (f'<div class="bm"{style}><span class="lab">{esc(label)}</span><span class="num">{esc(number)}</span>'
            f'<span class="bench">{esc(bench)}</span><p class="mean">{esc(mean)}</p></div>')


def row(text: str, date: str = "") -> str:
    return f'<div class="row"><span class="t">{esc(text)}</span><span class="date">{esc(date)}</span></div>' if date else f'<div class="row"><span class="t">{esc(text)}</span></div>'


def bars(pairs: list[tuple[str, float, str]]) -> list[str]:
    """One hbar per (label, count, figure), each as long as its count against the largest, which is marked top."""
    top = max((n for _label, n, _figure in pairs), default=0) or 1
    return [f'<div class="hbar"><span>{esc(label)}</span><span class="b{" top" if i == 0 else ""}" style="width:{100 * n / top:.1f}%"></span><span class="c">{esc(figure)}</span></div>'
            for i, (label, n, figure) in enumerate(pairs)]


def runs() -> list[dict]:
    """The validation runs the run log holds, each a dict with the time it ran at."""
    found = []
    for line in read_lines(failure_log.home() / "validate-runs.jsonl"):
        try:
            row_ = json.loads(line)
        except ValueError:
            continue
        if isinstance(row_, dict) and "at" in row_:
            found.append(row_)
    return found


def timing(last: dict) -> tuple[float, float]:
    return float(last.get("run") or 0), float(last.get("wait") or 0)


def queue_tile(found: list[dict]) -> str:
    # shortcut: the run row records time and queue wait only, so a pass or fail is not shown, when the row gains a result
    if not found:
        return tile("Test queue wait", "Not recorded", "", "Not recorded, because validate-runs.jsonl holds no run.")
    run, wait = timing(max(found, key=lambda r: r["at"]))
    return (f'<div class="bm"><span class="lab">Test queue wait</span><span class="num">{wait:.0f} s</span>'
            f'<div class="bullet"><span style="width:{100 * wait / (max(run, wait) or 1):.1f}%"></span><i style="left:{100 * run / (max(run, wait) or 1):.1f}%"></i></div>'
            f'<span class="bench">Against a {run:.0f} s test run</span>'
            f'<p class="mean">The latest run waited {wait:.0f} s for a slot, then ran for {run:.0f} s.</p></div>')


def failing(runs_: list[dict]) -> list[str]:
    return [str(r["name"]) for r in runs_ if r.get("conclusion") not in PASSING]


def checks_tile(github: dict | None) -> str:
    runs_ = (github or {}).get("checks")
    if runs_ is None:
        return tile("Checks on main", "Not recorded", "", "Not recorded, because no GitHub reading has been saved.")
    read = f"Read at {clock(github['read_at'])}." if github.get("read_at") else "Read time not recorded."
    if not runs_:
        return tile("Checks on main", "None", read, "No check is recorded on main.")
    names = failing(runs_)
    if names:
        return tile("Checks on main", "Failing", read, f"Failing: {', '.join(names)}.", ' style="background:var(--failbg)"')
    return tile("Checks on main", "Passing", read, f"All {len(runs_)} checks pass.")


def gates_tile(entries: list[tuple[str, str, str, str]]) -> str:
    if not entries:
        return tile("Gate blocks", "0", "", "No gate block is recorded.")
    gates = len({gate for _when, _repo, gate, _reason in entries})
    return tile("Gate blocks", f"{len(entries)}", f"By {gates} gates", "Each one was refused by a gate before it landed.")


def gate_bars(entries: list[tuple[str, str, str, str]]) -> str:
    counted = Counter(gate for _when, _repo, gate, _reason in entries).most_common()
    if not counted:
        return '<p class="small">No gate block is recorded.</p>'
    return f'<div>{fold(bars([(gate, n, str(n)) for gate, n in counted]), "gate blocks", SHOWN_GATES)}</div>'


def refusal_rows(entries: list[tuple[str, str, str, str]]) -> str:
    newest = sorted(entries, key=lambda row_: row_[0], reverse=True)[:MAX_REFUSALS]
    if not newest:
        return '<p class="small">No refusal is recorded.</p>'
    rows = [row(f"{gate} refused. {reason}", f"{when}, {repo}") for when, repo, gate, reason in newest]
    return f"<div>{fold(rows, 'refusals', SHOWN_REFUSALS)}</div>"


def test_suite(found: list[dict]) -> str:
    if not found:
        return '<p class="small">Not recorded, because validate-runs.jsonl holds no run.</p>'
    run, wait = timing(max(found, key=lambda r: r["at"]))
    return (f'<p class="mean">{len(found)} runs recorded. The latest took {run:.0f} s after waiting {wait:.0f} s for a free slot.</p>'
            f'<div class="stack" aria-label="Latest run: {wait:.0f} seconds waiting, {run:.0f} seconds running"><span style="flex:{wait:.0f};background:#C7C6CF"></span>'
            f'<span style="flex:{run:.0f};background:#17161C"></span></div>'
            f'<div class="keys"><span><span class="sw" style="background:#C7C6CF"></span>Waiting {wait:.0f} s</span>'
            f'<span><span class="sw" style="background:#17161C"></span>Running {run:.0f} s</span></div>')


def slowest() -> str:
    try:
        timings = json.loads((failure_log.home() / "validate-timings.json").read_text(encoding="utf-8"))
        top = sorted(((n, float(s)) for n, s in timings.items()), key=lambda kv: -kv[1])
    except (OSError, ValueError, AttributeError, TypeError):
        return '<p class="small">Not recorded, because validate-timings.json could not be read.</p>'
    if not top:
        return '<p class="small">No test file is timed.</p>'
    return f'<div>{fold(bars([(name, secs, f"{secs:.1f} s") for name, secs in top]), "slowest test files", SHOWN_SLOWEST)}</div>'


def lessons() -> str:
    found = []
    for path in sorted((failure_log.home() / "lessons").glob("*.jsonl")):
        for line in read_lines(path):
            try:
                row_ = json.loads(line)
            except ValueError:
                continue
            if isinstance(row_, dict) and row_.get("what"):
                found.append(row_)
    newest = sorted(found, key=lambda r: str(r.get("date") or ""), reverse=True)[:MAX_LESSONS]
    if not newest:
        return '<p class="small">No lesson is recorded.</p>'
    rows = [row(f"{r['what']}" + (f" Rule: {r['rule']}" if r.get("rule") else ""), str(r.get("date") or "date not recorded")) for r in newest]
    return f"<div>{fold(rows, 'lessons', SHOWN_LESSONS)}</div>"


def git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def version() -> str:
    installed, staging = git("rev-parse", "--short", "HEAD"), git("rev-parse", "--short", "origin/staging")
    if not installed or not staging:
        return row("Not recorded, because the installed commit or staging could not be read.")
    behind = git("rev-list", "--count", "HEAD..origin/staging")
    state = "level with staging" if installed == staging else f"{behind} commits behind staging" if behind else "different from staging"
    return row(f"Version: installed {installed}, staging {staging}: {state}.")


def hook_newest() -> float | None:
    try:
        return max(p.stat().st_mtime for p in (failure_log.home() / "hook-fires").iterdir())
    except (OSError, ValueError):
        return None


def hooks(newest: float | None) -> str:
    if newest is None:
        return row("Hook firing is not recorded.")
    return row(f"Hook firing is no longer recorded since {datetime.fromtimestamp(newest, timezone.utc):%d %b}.")


def lead(github: dict | None, newest: float | None) -> str:
    runs_ = (github or {}).get("checks")
    if runs_ is None:
        first = "The checks on main are not recorded."
    elif not runs_:
        first = "No check is recorded on main."
    elif failing(runs_):
        count = len(failing(runs_))
        first = f"{count} failing check{'s' if count != 1 else ''} on main."
    else:
        first = f"All {len(runs_)} checks on main pass."
    if newest is None:
        return first
    return f"{first} Hook firing is no longer recorded since {datetime.fromtimestamp(newest, timezone.utc):%d %b}, so the page cannot confirm the guards ran since then."


def render(data: dict) -> str:
    """The Health section as HTML, from the page's figures in DATA, in the mockup's markup and classes (docs/city/Main.dc.html)."""
    github, found, newest = data.get("github"), runs(), hook_newest()
    entries = failure_log.entries()
    tiles = checks_tile(github) + queue_tile(found) + gates_tile(entries)
    gates = card("Gate blocks", gate_bars(entries) + '<h3 style="padding-top:12px">Recent refusals</h3>' + refusal_rows(entries))
    suite = card("Test suite", test_suite(found) + slowest() + '<h3 style="padding-top:12px">Lessons</h3>' + lessons())
    records = f'<div class="card" style="grid-column:1/-1"><h3>Records</h3><div>{hooks(newest)}{version()}</div></div>'
    return ('<section class="chap" id="health" aria-labelledby="h0"><h2 id="h0">Health</h2>'
            f'<p class="read">{esc(lead(github, newest))}</p>'
            f'<div class="tiles">{tiles}</div>'
            f'<div class="grid2">{gates}{suite}{records}</div></section>')
