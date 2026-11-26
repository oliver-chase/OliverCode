"""City (#1335): one lean HTML page that tells the story of the work, drawn from the figures `olivercode status` prints, with no model call.

`olivercode status page [--root DIR]` writes `city.html` to the OliverCode home. The page leads with what needs the owner, then what is building, then what
landed today with its time and cost, then the landing rate and the estimated finish. The design is the archived one (editorial serif layout, lavender palette,
pastel status accents, status pills with a meaning, commands in purple). `render` reads only what it is given and calls nothing.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import cmd_status, failure_log, gh_budget, repo_state, run_lock

USAGE = "Usage: olivercode status page [--root DIR]"

STYLE = """
:root{--bg:#faf9f6;--card:#fff;--ink:#191820;--sub:#696772;--line:#e7e4e9;--lav:#C8BBD5;--lav-strong:#8E789F;
--good-bg:#edf4ef;--good-line:#c9ddcf;--good-ink:#315b40;--warn-bg:#fbf2e7;--warn-line:#ecd5b4;--warn-ink:#7a4f12;
--bad-bg:#fbeeee;--bad-line:#e9c4c4;--bad-ink:#8a2f2f;--idle-bg:#f1f0f3;--idle-line:#dcd9e0;--idle-ink:#5d5a66}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 Georgia,"Times New Roman",serif;overflow-x:hidden}
main{max-width:860px;margin:0 auto;padding:32px 16px 48px;display:grid;gap:18px}
h1,h2{font-weight:500;margin:0}h1{font-size:clamp(2rem,6vw,3rem);line-height:1.05;letter-spacing:-.04em}h2{font-size:1.4rem;letter-spacing:-.02em}
.eyebrow{font:600 10px/1.4 Arial,sans-serif;text-transform:uppercase;letter-spacing:.16em;color:var(--sub);margin-bottom:9px}
.sub{color:var(--sub)}p{margin:8px 0}
section{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:17px 18px;min-width:0}
section.run{border-left:4px solid var(--lav-strong)}section.idle{border-left:4px solid var(--idle-line)}section.need{border-left:4px solid var(--warn-line)}
.head{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:8px}
.pill{display:inline-block;border:1px solid var(--idle-line);padding:3px 8px;border-radius:3px;font:600 .72rem/1.4 Arial,sans-serif;background:var(--idle-bg);color:var(--idle-ink)}
.pill.good{border-color:var(--good-line);background:var(--good-bg);color:var(--good-ink)}
.pill.warn{border-color:var(--warn-line);background:var(--warn-bg);color:var(--warn-ink)}
.pill.bad{border-color:var(--bad-line);background:var(--bad-bg);color:var(--bad-ink)}
.pill.running{border-color:var(--lav-strong);background:var(--lav-strong);color:#fff}
ul{margin:0;padding:0;list-style:none}li{padding:9px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}li:first-child{border-top:0}
.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr))}
.big{font-size:2.2rem;line-height:1.05;letter-spacing:-.05em}
code{font:600 .86em ui-monospace,SFMono-Regular,Menlo,monospace;background:#eee8f3;border:1px solid #d7c9e2;color:#554565;padding:2px 6px;border-radius:3px;overflow-wrap:anywhere}
"""


def esc(text) -> str:
    """TEXT escaped, with each `command` in backticks shown in purple."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(str(text), quote=True))


def items(lines: list[str], none: str) -> str:
    return "<ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines or [none]) + "</ul>"


def block(css: str, title: str, pill: tuple[str, str], body: str) -> str:
    return f'<section class="{css}"><div class="head"><h2>{esc(title)}</h2><span class="pill {pill[1]}">{esc(pill[0])}</span></div>{body}</section>'


def landed_row(row: dict) -> str:
    cost = f"${row['cost']:.2f}" if row["cost"] else "cost not recorded"
    return f"#{row['story'].rsplit('-', 1)[-1]} in {row['repo']} landed at {datetime.fromtimestamp(row['at'], timezone.utc):%H:%M} UTC, {cmd_status.minutes(row['total'])}, {cost}"


def gather(slug: str, now: datetime, open_now: int | None, rows: list[dict] | None, waiting: list[str], log: list[dict] | None, claims: dict, alive: bool,
           holder: dict | None = None) -> dict:
    """The page's figures from the functions `olivercode status` uses. A figure that was not read is None or the word unknown, and none is guessed."""
    stamp = now.timestamp()
    building, warnings = cmd_status.building_block(stamp, claims, log or [], alive, open_now, holder) if log is not None else (["Building: unknown, because the run log could not be read."], [])
    done = cmd_status.landed_today(log, stamp) if log is not None else None
    pace = (f"{slug}: " + cmd_status.summary(open_now, rows, now)) if open_now is not None and rows is not None else \
        f"Landing rate and finish date: unknown, because the issues of {slug} were not read from GitHub."
    return {"slug": slug, "now": now, "open": open_now, "waiting": waiting, "building": building, "warnings": warnings, "busy": bool(claims) and alive,
            "landed": done, "pace": pace}


def render(data: dict) -> str:
    """The whole page as one HTML string."""
    need, busy, landed = data["waiting"] + data["warnings"], data["busy"], data["landed"]
    cost = sum(r["cost"] for r in landed or [])
    count = "unknown" if data["open"] is None else str(data["open"])
    parts = [
        block("need" if need else "", "Needs you", ("Needs you", "warn") if need else ("Nothing waiting", "good"), items(need, "Nothing needs you right now.")),
        block("run" if busy else "idle", "Building", ("Running", "running") if busy else ("Idle", "idle"), items(data["building"], "No story is building.")),
        block("", "Landed today", ("Landed", "good") if landed else ("None yet", "idle") if landed is not None else ("Unknown", "bad"),
              items([landed_row(r) for r in landed] if landed else [], "Nothing has landed today.") +
              (f'<p class="sub">{len(landed)} landed for ${cost:.2f} today.</p>' if landed else "")),
        block("", "Pace", ("Open " + count, "idle" if data["open"] is not None else "bad"), f'<div class="cards"><div><div class="big">{esc(count)}</div>'
              f'<div class="sub">stories open</div></div></div><p>{esc(data["pace"])}</p>'
              '<p class="sub">The landing rate counts stories closed as completed in the last 7 days. The finish date is an estimate.</p>'),
    ]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OliverCode City</title>'
            f'<style>{STYLE}</style></head><body><main><header><div class="eyebrow">OliverCode · {esc(data["slug"])}</div><h1>The work today</h1>'
            f'<p class="sub">Updated {data["now"]:%Y-%m-%d %H:%M} UTC. Refresh it with `olivercode status page`.</p></header>{"".join(parts)}</main></body></html>')


def page_path() -> Path:
    return failure_log.home() / "city.html"


def write(slug: str | None, count=None, fetch=cmd_status.recent, now: datetime | None = None, out=print, waiting=cmd_status.waiting_lines) -> int:
    """Write the page. The exit code is 1 when a GitHub figure could not be read, though the page is still written and names it unknown."""
    if not slug:
        out("Error: this repo has no GitHub origin.")
        return 1
    held = gh_budget.refusal("rest")
    if held:
        out(held)
        return 1
    now = now or datetime.now(timezone.utc)
    open_now = (count or cmd_status.issue_count.count_issues)(slug, "open")
    rows = fetch(slug, now - timedelta(days=cmd_status.DAYS))
    try:
        log = cmd_status.run_log()
    except (OSError, ValueError):
        log = None
    stamp = now.timestamp()
    data = gather(slug, now, open_now, rows, waiting(), log, cmd_status.live_claims(stamp), cmd_status.runner_alive(), run_lock.active(slug, stamp))
    failure_log.write_atomic(page_path(), render(data))
    out(f"City written to {page_path()}.")
    return 0 if open_now is not None and rows is not None else 1


def command_page(argv: list[str]) -> int:
    root = Path.cwd()
    if argv[:1] == ["--root"] and len(argv) == 2:
        root = Path(argv[1]).expanduser()
    elif argv:
        print(USAGE)
        return 1
    return write(repo_state.origin(root))
