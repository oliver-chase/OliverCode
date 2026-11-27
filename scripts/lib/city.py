"""City v2 (#1356): the page's frame, drawn only from local files, with no GitHub call and no model call.

`olivercode status page [--fetch] [--root DIR]` writes `city.html` to the OliverCode home. Every write reads the run log, the owner queue, the board copy
that `board sync` keeps and `city-github.json`. Only `--fetch` calls GitHub: it reads the opened and closed counts and the check results once and saves them
to `city-github.json` with the time read. The frame is a nav (Today, Delivery, Cost, Health) and a status band that gives the run state, the builder count,
the needs-you count, the Updated time and a Refresh control. The page reloads itself every 60 seconds. The Delivery, Cost and Health sections each render in
their own module.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import city_cost, city_delivery, city_health, cmd_owner, cmd_status, failure_log, gh_budget, local_config, repo_state, run_lock

USAGE = "Usage: olivercode status page [--fetch] [--root DIR]"
STALE_SECONDS = 600
SHOWN = 5  # owner-queue steps the page lists before it says how many more

STYLE = """
:root{--field:#F6F6F7;--card:#fff;--ink:#17161C;--muted:#5D5C66;--accent:#4C3FB0;--asoft:#EEECF8;--warn:#8A4B00;--warnbg:#FBEEDD;--fail:#B3261E;--failbg:#FAE6E4;
--ok:#2B7A4B;--idle:#5F5E69;--idlebg:#ECECEF;--line:rgb(23 22 28/.10)}
*{box-sizing:border-box}
body{margin:0;background:var(--field);color:var(--ink);font:16px/1.5 Inter,system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;overflow-x:hidden}
h1,h2,h3{font-family:Newsreader,Georgia,serif;font-weight:400;margin:0}h2{font-size:28px}h3{font:500 15px/1.4 Inter,system-ui,sans-serif}p{margin:0}
a{color:var(--accent)}.small{font-size:14px;color:var(--muted)}
.wrap{max-width:1360px;margin:0 auto;padding:0 max(16px,2.5vw)}
.bar{background:var(--card);box-shadow:0 1px 0 var(--line)}.barin{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;padding-block:12px}
.brand{font:500 26px Newsreader,Georgia,serif}.nav{display:flex;flex-wrap:wrap;gap:4px;flex:1 1 auto}
.nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;border-radius:999px;color:var(--ink);text-decoration:none;font-size:15px}
.nav a:first-child{background:var(--asoft);color:var(--accent);font-weight:500}
.status{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;font-size:14px}
.pill{display:inline-flex;align-items:center;gap:8px;padding:5px 13px;border-radius:999px;font-size:14px;font-weight:500;background:var(--card);white-space:nowrap}
.pill i{width:8px;height:8px;border-radius:50%;background:currentColor}
.c-run{color:var(--accent)}.c-idle{color:var(--idle)}.c-wait{color:var(--warn)}.c-fail{color:var(--fail)}
.b-run{background:var(--asoft)}.b-idle{background:var(--idlebg)}.b-wait{background:var(--warnbg)}.b-fail{background:var(--failbg)}
.band{border-radius:16px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}.band .pill{align-self:flex-start}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 16px;border-radius:999px;border:0;font:500 15px Inter,system-ui,sans-serif;
background:var(--card);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line);cursor:pointer}
.body{display:flex;flex-direction:row-reverse;flex-wrap:wrap;gap:32px;align-items:flex-start;padding-block:32px 64px}
.rail{flex:1 1 340px;max-width:420px;min-width:0;display:flex;flex-direction:column;gap:16px}
.main{flex:999 1 600px;min-width:0;display:flex;flex-direction:column;gap:48px}
.card{background:var(--card);border-radius:20px;padding:20px;display:flex;flex-direction:column;gap:12px;min-width:0}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.cnt{font-size:14px;font-weight:500;color:var(--warn);background:var(--warnbg);padding:2px 10px;border-radius:999px}
.step{display:flex;flex-direction:column;gap:6px;padding:10px 0;overflow-wrap:anywhere}.step+.step{box-shadow:0 -1px 0 var(--line)}
.acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
code{font:13px ui-monospace,"SF Mono",Menlo,monospace;background:var(--field);padding:8px 10px;border-radius:10px;overflow-wrap:anywhere}
.chap{display:flex;flex-direction:column;gap:12px}.chap>h2{font-size:40px;line-height:1.1}
.count{font:40px/1 Newsreader,Georgia,serif}
@media (max-width:600px){.body{flex-direction:column;padding-block:16px 40px}.rail{max-width:none;width:100%}.chap>h2{font-size:30px}}
"""

SCRIPT = """
var w=+document.body.dataset.written,age=Math.floor(Date.now()/1000-w),old=document.getElementById("stale");
if(age>%d){old.hidden=false;old.querySelector("p").textContent="This page is "+(age>=7200?Math.floor(age/3600)+" hours":Math.floor(age/60)+" minutes")+" old, so the figures may have changed. Refresh to rebuild it with the command below."}
document.addEventListener("click",function(e){var b=e.target.closest("[data-copy]");if(b&&navigator.clipboard){navigator.clipboard.writeText(b.dataset.copy);b.textContent="Copied"}
if(e.target.closest("#refresh"))location.reload()});
""" % STALE_SECONDS


def esc(text) -> str:
    """TEXT escaped, with each `command` in backticks shown as a command."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(str(text), quote=True))


def command(text: str) -> str:
    """A command to copy, since a page opened from a file cannot run it."""
    return f'<div class="acts"><code>{esc(text)}</code><button class="btn" data-copy="{html.escape(text, quote=True)}">Copy</button></div>'


def landed_row(row: dict) -> str:
    cost = f"${row['cost']:.2f}" if row["cost"] else "cost not recorded"
    return f"#{row['story'].rsplit('-', 1)[-1]} in {row['repo']} landed at {datetime.fromtimestamp(row['at'], timezone.utc):%H:%M} UTC, {cmd_status.minutes(row['total'])}, {cost}"


def github_path() -> Path:
    return failure_log.home() / "city-github.json"


def saved_github() -> dict | None:
    """The figures `--fetch` saved, or None when it has not run or the file cannot be read."""
    try:
        found = json.loads(github_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def read_github(slug: str, now: datetime, count=None, fetch=cmd_status.recent, runner=cmd_status.issue_count.gh_list) -> dict:
    """The one GitHub read: opened and closed counts over the last week and the check results on staging. A figure that could not be read is None."""
    open_now = (count or cmd_status.issue_count.count_issues)(slug, "open")
    rows = fetch(slug, now - timedelta(days=cmd_status.DAYS))
    since = now - timedelta(days=cmd_status.DAYS)
    figures = {"slug": slug, "read_at": now.timestamp(), "open": open_now, "opened": None, "closed": None, "checks": None}
    if rows is not None:
        figures["opened"] = sum(1 for r in rows if cmd_status._after(r.get("created_at"), since))
        figures["closed"] = sum(1 for r in rows if r.get("state_reason") == "completed" and cmd_status._after(r.get("closed_at"), since))
    done = runner([f"repos/{slug}/commits/staging/check-runs?per_page=100"])
    try:
        runs = json.loads(done.stdout)["check_runs"] if done.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        runs = None
    if runs is not None:
        figures["checks"] = [{"name": r.get("name"), "conclusion": r.get("conclusion") or r.get("status")} for r in runs]
    return figures


def board_ready(root: Path, slug: str) -> int | None:
    """The stories in Ready on the local board copy that `board sync` keeps, or None when there is no copy or no config to find it."""
    try:
        config = local_config.backlog_config(root)
        items = json.loads((gh_budget.home() / f"board-{config['projectOwner']}-{config['projectNumber']}.json").read_text(encoding="utf-8"))
        return sum(1 for i in items if str(i.get("status", "")).lower() == "ready" and (i.get("content") or {}).get("repository", slug) == slug)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def needs() -> list[dict]:
    """The open owner-queue steps."""
    try:
        cmd_owner.retire_removed()
        return cmd_owner.open_items()
    except (OSError, ValueError, KeyError):
        return []


def gather(slug: str, now: datetime, steps: list[dict], log: list[dict] | None, claims: dict, alive: bool, holder: dict | None, ready: int | None,
           github: dict | None) -> dict:
    """The page's figures from local files. A figure that was not read is None, and none is guessed."""
    stamp = now.timestamp()
    building, warnings = cmd_status.building_block(stamp, claims, log, alive, None, holder) if log is not None else (["Building: unknown, because the run log could not be read."], [])
    busy = bool(claims) and alive
    return {"slug": slug, "now": now, "steps": steps, "building": building, "warnings": warnings, "busy": busy, "builders": len(claims) if busy else 0,
            "landed": cmd_status.landed_today(log, stamp) if log is not None else None, "ready": ready, "github": github, "log": log,
            "until": gh_budget.blocked_until("")}


def state(data: dict) -> tuple[str, str, str]:
    """(css, word, sentence) for the band: waiting on GitHub, stopped, running, idle with work Ready or idle with nothing Ready."""
    if data["until"]:
        when = datetime.fromtimestamp(data["until"], timezone.utc)
        return "wait", "Waiting", f"GitHub's hourly budget is used up, so the drain is paused until about {when:%H:%M} UTC and will carry on by itself."
    if data["warnings"]:
        return "fail", "Stopped", data["warnings"][0].removeprefix("Warning: ")
    n = data["builders"]
    if data["busy"]:
        return "run", "Building", f"{n} builder{' is' if n == 1 else 's are'} working. The stories are listed under Building now."
    ready = data["ready"]
    if ready:
        return "idle", "Idle", f"No drain is running. {ready} {'story is' if ready == 1 else 'stories are'} Ready, so starting the drain would take them in priority order."
    if ready is None:
        return "idle", "Idle", "No drain is running. The Ready count is not recorded, because the board copy was not read."
    return "idle", "Idle", "No drain is running, and no story is Ready. The drain has nothing to take until a story is marked Ready."


def needs_card(data: dict) -> str:
    steps = data["steps"]
    lines = "".join(f'<div class="step"><h3>#{esc(s.get("id"))} {esc(s.get("step"))}</h3></div>' for s in steps[:SHOWN])
    more = f'<p class="small">and {len(steps) - SHOWN} more. See them with `olivercode owner`.</p>' if len(steps) > SHOWN else ""
    count = f'<span class="cnt">{len(steps)}</span>' if steps else ""
    body = lines + more if steps else '<p>Nothing waits on you.</p>'
    return f'<div class="card" id="needs"><div class="head"><h2>Needs you</h2>{count}</div>{body}</div>'


def building_card(data: dict) -> str:
    lines = "".join(f'<div class="step"><p>{esc(line)}</p></div>' for line in data["building"] + data["warnings"])
    ready = data["ready"]
    queued = "Ready count: not recorded, because the board copy was not read." if ready is None else f"{ready} {'story is' if ready == 1 else 'stories are'} Ready."
    return (f'<div class="card" id="live"><h2>Building now</h2>{lines}<p class="small">{queued}</p>'
            f'{command("olivercode drain REPO")}</div>')


def today(data: dict) -> str:
    landed, github = data["landed"], data["github"]
    cost = sum(r["cost"] for r in landed or [])
    rows = [landed_row(r) for r in landed] if landed else ["Nothing has landed today." if landed is not None else "Landed today: unknown, because the run log could not be read."]
    parts = []
    if github and github.get("open") is not None:
        parts.append(f"{github['open']} open.")
    if github and github.get("opened") is not None and github.get("closed") is not None:
        parts.append(f"In the last {cmd_status.DAYS} days {github['closed']} closed as completed and {github['opened']} opened.")
    if parts:
        pace = " ".join(parts)
        read = f"Read from GitHub at {datetime.fromtimestamp(github['read_at'], timezone.utc):%H:%M} UTC."
    else:
        pace, read = "Open count and landing rate: not recorded yet.", "Run `olivercode status page --fetch` to read them from GitHub once."
    total = f'<p class="small">{len(landed)} landed for ${cost:.2f} today.</p>' if landed else ""
    return (f'<section class="chap" id="today"><h2>Today</h2><div class="card"><h3>Landed today</h3>{"".join(f"<p>{esc(r)}</p>" for r in rows)}{total}</div>'
            f'<div class="card"><h3>Pace</h3><p>{esc(pace)}</p><p class="small">{esc(read)}</p></div></section>')


def render(data: dict) -> str:
    """The whole page as one HTML string."""
    css, word, sentence = state(data)
    now, steps = data["now"], data["steps"]
    chips = f'<span>{data["builders"]} builder{"" if data["builders"] == 1 else "s"}</span>' + (f'<a href="#needs">{len(steps)} need you</a>' if steps else "")
    start = command("olivercode drain REPO") if css == "idle" else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="refresh" content="60"><title>OliverCode City</title>'
            f'<style>{STYLE}</style></head><body data-written="{int(now.timestamp())}"><div class="city"><header class="bar"><div class="wrap barin">'
            '<span class="brand">OliverCode City</span><nav class="nav" aria-label="Sections"><a href="#today">Today</a><a href="#delivery">Delivery</a>'
            '<a href="#cost">Cost</a><a href="#health">Health</a></nav>'
            f'<div class="status" aria-label="System status"><span class="pill c-{css}"><i></i>{word}</span>{chips}<span>Updated {now:%H:%M} UTC</span>'
            '<button class="btn" id="refresh">Refresh</button></div></div></header>'
            f'<div class="wrap"><div class="band b-{css}" style="margin-top:16px"><span class="pill c-{css}"><i></i>{word}</span><p>{esc(sentence)}</p>{start}</div>'
            '<div class="band b-wait" id="stale" hidden style="margin-top:16px"><span class="pill c-wait"><i></i>Out of date</span><p></p>'
            f'{command("olivercode status page")}</div></div>'
            f'<div class="wrap body"><aside class="rail" aria-label="Live status">{needs_card(data)}{building_card(data)}</aside>'
            f'<main class="main">{today(data)}{city_delivery.render(data)}{city_cost.render(data)}{city_health.render(data)}</main></div></div>'
            f'<script>{SCRIPT}</script></body></html>')


def page_path() -> Path:
    return failure_log.home() / "city.html"


def write(slug: str | None, root: Path | None = None, fetch: bool = False, now: datetime | None = None, out=print, waiting=needs, read=read_github) -> int:
    """Write the page from local files. With FETCH it first reads GitHub once and saves the figures. The exit code is 1 when FETCH could not read a figure,
    though the page is still written and names it not recorded."""
    if not slug:
        out("Error: this repo has no GitHub origin.")
        return 1
    now = now or datetime.now(timezone.utc)
    root = root or Path.cwd()
    unread = False
    if fetch:
        held = gh_budget.refusal("rest")
        if held:
            out(held)
            return 1
        figures = read(slug, now)
        unread = None in figures.values()
        failure_log.write_atomic(github_path(), json.dumps(figures))
    github = saved_github()
    github = github if github and github.get("slug") == slug else None
    try:
        log = cmd_status.run_log()
    except (OSError, ValueError):
        log = None
    stamp = now.timestamp()
    data = gather(slug, now, waiting(), log, cmd_status.live_claims(stamp), cmd_status.runner_alive(), run_lock.active(slug, stamp), board_ready(root, slug), github)
    failure_log.write_atomic(page_path(), render(data))
    out(f"City written to {page_path()}.")
    return 1 if unread else 0


def refresh(root: Path | None = None) -> int:
    """Rewrite the page from local files, quietly. The drain calls it (#1350)."""
    root = root or Path.cwd()
    return write(repo_state.origin(root), root, out=lambda text: None)


def command_page(argv: list[str]) -> int:
    root, fetch = Path.cwd(), False
    args = list(argv)
    if "--fetch" in args:
        args.remove("--fetch")
        fetch = True
    if args[:1] == ["--root"] and len(args) == 2:
        root = Path(args[1]).expanduser()
    elif args:
        print(USAGE)
        return 1
    return write(repo_state.origin(root), root, fetch=fetch)
