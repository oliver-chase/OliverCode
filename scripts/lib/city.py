"""City v2: the page's frame, drawn only from local files, with no GitHub call and no model call.

`olivercode status page [--fetch] [--open] [--root DIR]` writes `city.html` to the OliverCode home, and --open shows it in the default browser. Every write reads the run log, the owner queue, the board copy
that `board sync` keeps and `city-github.json`. Only `--fetch` calls GitHub: it reads the opened and closed counts and the check results once and saves them
to `city-github.json` with the time read. The frame is a nav (Today, Delivery, Cost, Health) and a status band that gives the run state, the builder count,
the needs-you count, the Updated time and a Refresh control. The markup and stylesheet are the mockup's, in docs/city. The page reloads itself every 60 seconds. The Delivery, Cost and Health sections each render in
their own module. The Live rail shows a card for each working builder, the queue, and Needs you with the latest owner decision. The Today section opens with the date, a headline, a paragraph and four answers.
"""

from __future__ import annotations

import html
import json
import re
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import agent_loop, city_cost, city_delivery, city_health, cmd_owner, cmd_status, failure_log, gh_budget, local_config, relay, repo_state, run_lock
from lib.city_health import money

USAGE = "Usage: olivercode status page [--fetch] [--open] [--root DIR]"
STALE_SECONDS = 600
SHOWN = 3  # owner-queue steps the page lists before it says how many more
STAGE_LABELS = ("Claimed", "Building", "Validating", "Landing", "Landed")  # the builder card's track, in the order cmd_status.STAGES names them

STYLE = """
body{margin:0}
a{color:#4C3FB0}a:hover{color:#2F2580}
.city{--field:#F6F6F7;--card:#FFFFFF;--ink:#17161C;--muted:#5D5C66;--accent:#4C3FB0;--asoft:#EEECF8;--data:#C7C6CF;--data2:#8F8E99;--none:#EFEFF1;--ok:#2B7A4B;--okbg:#E6F2EA;--warn:#8A4B00;--warnbg:#FBEEDD;--fail:#B3261E;--failbg:#FAE6E4;--idle:#5F5E69;--idlebg:#ECECEF;--line:rgb(23 22 28 / .10);font-family:Inter,system-ui,-apple-system,sans-serif;font-size:16px;line-height:1.5;color:var(--ink);background:var(--field);font-variant-numeric:tabular-nums;min-height:100%}
.city ::selection{background:#DCD8F2}
.city :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3{font-family:Newsreader,Georgia,serif;font-weight:400;margin:0;text-wrap:balance}
p{margin:0}
.wrap{max-width:1360px;margin:0 auto;box-sizing:border-box;padding-left:max(16px,2.5vw);padding-right:max(16px,2.5vw)}
.bar{background:var(--card);box-shadow:0 1px 0 var(--line)}
.barin{display:flex;flex-wrap:wrap;gap:12px 32px;align-items:center;padding-block:14px}
.brand{font-family:Newsreader,Georgia,serif;font-size:26px;font-weight:500}
.nav{display:flex;flex-wrap:wrap;gap:4px;flex:1 1 auto}
.nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;border-radius:999px;color:var(--ink);text-decoration:none;font-size:15px}
.nav a.on{background:var(--asoft);color:var(--accent);font-weight:500}
.status{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;font-size:14px;font-weight:500;white-space:nowrap}
.pill i{width:8px;height:8px;border-radius:50%;background:currentColor}
.p-run{background:var(--asoft);color:var(--accent)}
.p-fail{background:var(--failbg);color:var(--fail)}
.p-warn{background:var(--warnbg);color:var(--warn)}
.p-ok{background:var(--okbg);color:var(--ok)}
.p-idle{background:var(--idlebg);color:var(--idle)}
.chipl{display:inline-flex;align-items:center;min-height:36px;padding:0 12px;border-radius:999px;font-size:14px;color:var(--ink);text-decoration:none;box-shadow:inset 0 0 0 1px var(--line)}
.chipl.warn{color:var(--warn);box-shadow:inset 0 0 0 1px #E9CFA9}
.upd{display:inline-flex;align-items:center;gap:8px;font-size:14px;color:var(--muted);padding:0 4px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border-radius:999px;border:0;font:inherit;font-size:15px;font-weight:500;cursor:pointer;text-decoration:none;white-space:nowrap}
.b-pri{background:var(--ink);color:#fff}
.b-acc{background:var(--accent);color:#fff}
.b-ghost{background:var(--card);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
.btn[disabled]{background:var(--idlebg);color:var(--idle);cursor:not-allowed;box-shadow:none}
.body{display:flex;flex-direction:row-reverse;flex-wrap:wrap;gap:32px;align-items:flex-start;padding-block:40px 80px}
.rail{flex:1 1 340px;max-width:420px;min-width:0;display:flex;flex-direction:column;gap:16px}
.main{flex:999 1 600px;min-width:0;display:flex;flex-direction:column;gap:64px}
.card{background:var(--card);border-radius:20px;padding:22px;display:flex;flex-direction:column;gap:12px;min-width:0;box-shadow:0 1px 2px rgb(23 22 28 / .05)}
.railhead{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.railhead h2{font-size:28px}
.small{font-size:14px;color:var(--muted)}
.band{background:var(--asoft);border-radius:16px;padding:16px;display:flex;flex-direction:column;gap:8px}
.band .pill{align-self:flex-start;background:var(--card)}
.bld{display:flex;flex-direction:column;gap:12px;padding-top:4px}
.bld+.bld{padding-top:16px;box-shadow:0 -1px 0 var(--line)}
.bhead{display:flex;gap:10px;justify-content:space-between;align-items:flex-start}
.n{font-weight:500;color:var(--accent);text-decoration:none}
.btitle{font-size:15px;font-weight:500;line-height:1.4;margin-top:2px}
.tags{display:flex;gap:4px;flex:none}
.tag{font-size:12px;font-weight:500;padding:2px 8px;border-radius:999px;background:var(--idlebg);color:var(--ink)}
.tag.p0{background:var(--failbg);color:var(--fail)}
.track{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));font-size:12px;color:var(--muted)}
.track li{position:relative;padding-top:20px;text-align:center}
.track li::before{content:"";position:absolute;top:3px;left:50%;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:#DDDCE3;z-index:1}
.track li::after{content:"";position:absolute;top:8px;right:50%;width:100%;height:2px;background:#DDDCE3}
.track li:first-child::after{display:none}
.track li.done::before,.track li.done::after,.track li.now::after{background:var(--ink)}
.track li.now::before{background:var(--accent);box-shadow:0 0 0 4px #DCD8F2}
.track li.now{color:var(--accent);font-weight:500}
.kv{display:grid;grid-template-columns:110px minmax(0,1fr);gap:6px 12px;font-size:14px}
.kv dt{color:var(--muted)}
.kv dd{margin:0}
.meter{height:6px;border-radius:999px;background:var(--idlebg);overflow:hidden;margin-top:4px}
.meter span{display:block;height:100%;background:var(--ink)}
.step{display:flex;flex-direction:column;gap:8px;padding:14px 0}
.step+.step{box-shadow:0 -1px 0 var(--line)}
.step h3{font-family:Inter,system-ui,sans-serif;font-size:15px;font-weight:500;line-height:1.4}
.acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
code{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;background:var(--field);padding:8px 10px;border-radius:10px;color:var(--ink)}
.date{font-size:13px;color:var(--muted)}
.lede{display:flex;flex-direction:column;gap:20px}
.lede h1{font-size:56px;line-height:1.05;max-width:900px}
.read{font-family:Newsreader,Georgia,serif;font-size:22px;line-height:1.45;max-width:760px}
.answers{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:16px;padding-top:8px}
.ans{display:flex;flex-direction:column;gap:6px;padding-top:14px;box-shadow:0 -2px 0 var(--ink)}
.ans .q{font-size:14px;color:var(--muted)}
.ans .a{font-family:Newsreader,Georgia,serif;font-size:28px;line-height:1.15}
.ans .e{font-size:14px;color:var(--muted)}
.chap{display:flex;flex-direction:column;gap:20px}
.chap>h2{font-size:40px;line-height:1.1}
.chap>.read{font-size:20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:16px}
.bm{background:var(--card);border-radius:20px;padding:20px;display:flex;flex-direction:column;gap:8px;min-width:0;box-shadow:0 1px 2px rgb(23 22 28 / .05)}
.bm .lab{font-size:14px;color:var(--muted)}
.bm .num{font-family:Newsreader,Georgia,serif;font-size:42px;line-height:1.05}
.bullet{position:relative;height:8px;border-radius:999px;background:var(--idlebg);margin:6px 0 2px}
.bullet span{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:var(--ink)}
.bullet i{position:absolute;top:-5px;width:2px;height:18px;background:var(--accent)}
.bench{font-size:13px;color:var(--accent);font-weight:500}
.mean{font-size:14px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:16px;align-items:start}
.card h3{font-size:24px;line-height:1.2}
.controls{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;justify-content:space-between}
.seg{display:inline-flex;flex-wrap:wrap;background:var(--card);border-radius:999px;padding:4px;gap:2px;box-shadow:inset 0 0 0 1px var(--line)}
.seg button{min-height:36px;min-width:44px;padding:0 14px;border:0;border-radius:999px;background:transparent;font:inherit;font-size:14px;color:var(--muted);cursor:pointer}
.seg button.on{background:var(--ink);color:#fff;font-weight:500}
.chart{position:relative;height:240px;display:flex;align-items:flex-end;gap:3px;padding-top:28px;box-shadow:0 1px 0 var(--line)}
.col{flex:1 1 0;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}
.barv{position:relative;border-radius:4px 4px 0 0;min-height:0}
.peak{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);padding-bottom:4px;font-size:13px;font-weight:500;white-space:nowrap;color:var(--ink)}
.xl{display:flex;gap:3px}
.xl span{flex:1 1 0;min-width:0;font-size:12px;color:var(--muted);white-space:nowrap;overflow:visible;padding-top:8px}
.avg{position:absolute;left:0;right:0;border-top:1.5px dashed var(--accent);pointer-events:none}
.avg span{position:absolute;right:0;bottom:2px;font-size:12px;color:var(--accent);font-weight:500;background:var(--card);padding:0 4px}
.stack{display:flex;height:14px;border-radius:999px;overflow:hidden;gap:2px}
.keys{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:14px}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}
.hbar{display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr) 48px;gap:12px;align-items:center;padding:5px 0;font-size:14px}
.hbar .b{height:10px;border-radius:999px;background:var(--data)}
.hbar .b.top{background:var(--ink)}
.hbar .c{text-align:right;font-weight:500}
.row{display:flex;flex-wrap:wrap;gap:4px 16px;align-items:baseline;padding:11px 0;font-size:15px}
.row+.row{box-shadow:0 -1px 0 var(--line)}
.row .t{flex:1 1 220px;min-width:0}
.tablebox{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:480px;font-size:14px}
th{font-weight:500;font-size:13px;color:var(--muted);text-align:left;padding:6px 12px 6px 0}
td{padding:9px 12px 9px 0;box-shadow:0 -1px 0 var(--line)}
.r{text-align:right}
.note{background:var(--warnbg);color:#5E3300;border-radius:14px;padding:12px 16px;font-size:15px}
.sizerow{display:grid;grid-template-columns:36px minmax(0,1fr);gap:14px;align-items:center;padding:10px 0}
.sizerow+.sizerow{box-shadow:0 -1px 0 var(--line)}
.lane{position:relative;height:40px}
.lane .base{position:absolute;left:0;right:0;top:12px;height:6px;border-radius:999px;background:var(--idlebg)}
.lane .rng{position:absolute;top:12px;height:6px;background:var(--data);border-radius:999px}
.lane .med,.lane .hi{position:absolute;top:7px;width:16px;height:16px;margin-left:-8px;border-radius:50%}
.lane .med{background:var(--ink)}
.lane .hi{background:#fff;box-shadow:inset 0 0 0 3px var(--ink)}
.lane .lim{position:absolute;top:2px;width:2px;height:26px;background:var(--accent)}
.lane small{position:absolute;top:26px;font-size:12px;color:var(--muted);white-space:nowrap;transform:translateX(-50%)}
.split{display:flex;height:32px;border-radius:10px;overflow:hidden;gap:2px;font-size:13px;font-weight:500}
.split span{display:flex;align-items:center;padding:0 10px;white-space:nowrap;overflow:hidden}
.hooks{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(190px,100%),1fr));gap:8px}
.hook{border-radius:12px;padding:10px 12px;background:var(--idlebg);display:flex;flex-direction:column;gap:2px;font-size:13px;color:var(--muted)}
.hook b{font-weight:500;font-size:14px;color:var(--ink)}
.gtrack{position:relative;height:12px;border-radius:999px;background:var(--idlebg)}
.gtrack span{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:var(--ok)}
.gtrack i{position:absolute;left:10%;top:-5px;width:2px;height:22px;background:var(--warn)}
.ghead{display:flex;justify-content:space-between;gap:12px;font-size:14px}
.more{font-weight:500;font-size:15px;min-height:44px;display:flex;align-items:center}
.fold[hidden]{display:none}
@media (max-width:600px){.body{flex-direction:column;padding-block:16px 40px}.rail{max-width:none;width:100%}.card{padding:18px}.lede h1{font-size:30px}.read{font-size:18px}.chap>h2{font-size:30px}.answers{grid-template-columns:repeat(2,minmax(0,1fr))}.ans .a{font-size:22px}.bm .num{font-size:34px}.brand{font-size:22px}.main{gap:40px}}
"""

FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&amp;family=Newsreader:opsz,wght@6..72,400;6..72,500&amp;display=swap">'

SCRIPT = """
var w=+document.body.dataset.written,age=Math.floor(Date.now()/1000-w),old=document.getElementById("stale");
if(age>%d){old.hidden=false;old.querySelector("p").textContent="This page is "+(age>=7200?Math.floor(age/3600)+" hours":Math.floor(age/60)+" minutes")+" old, so the figures may have changed. Refresh to rebuild it with the command below."}
document.addEventListener("click",function(e){var b=e.target.closest("[data-copy]");if(b&&navigator.clipboard){navigator.clipboard.writeText(b.dataset.copy);b.textContent="Copied"}
var f=e.target.closest("[data-fold]");if(f){e.preventDefault();var o=f.previousElementSibling;o.hidden=!o.hidden;f.textContent=o.hidden?f.dataset.fold:"Show fewer";keep()}
var v=e.target.closest("[data-view]");if(v)setTimeout(keep,0);
if(e.target.closest("#refresh"))location.reload()});
function keep(){try{sessionStorage.setItem("city",JSON.stringify({open:[].map.call(document.querySelectorAll("[data-fold]"),function(f){return !f.previousElementSibling.hidden}),
view:(document.querySelector("[data-view][aria-pressed=\\"true\\"]")||{dataset:{}}).dataset.view||"",y:scrollY}))}catch(x){}}
try{var s=JSON.parse(sessionStorage.getItem("city")||"{}");[].forEach.call(document.querySelectorAll("[data-fold]"),function(f,i){if(s.open&&s.open[i]){f.previousElementSibling.hidden=false;f.textContent="Show fewer"}});
var w2=s.view&&document.querySelector('[data-view="'+s.view+'"]');if(w2)w2.click();scrollTo(0,s.y||0)}catch(x){}
addEventListener("scroll",function(){clearTimeout(keep.t);keep.t=setTimeout(keep,150)});
""" % STALE_SECONDS


def esc(text) -> str:
    """TEXT escaped, with each `command` in backticks shown as a command."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", city_health.esc(text))


def command(text: str, label: str = "Copy") -> str:
    """A command to copy, since a page opened from a file cannot run it. LABEL names the button."""
    return f'<div class="acts"><code>{esc(text)}</code><button class="btn b-ghost" data-copy="{html.escape(text, quote=True)}">{label}</button></div>'


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
    """The one GitHub read: opened and closed counts over the last week and the check results on main (CI runs on main only). A figure that could not be read is None."""
    open_now = (count or cmd_status.issue_count.count_issues)(slug, "open")
    rows = fetch(slug, now - timedelta(days=cmd_status.DAYS))
    since = now - timedelta(days=cmd_status.DAYS)
    figures = {"slug": slug, "read_at": now.timestamp(), "open": open_now, "opened": None, "closed": None, "checks": None}
    if rows is not None:
        figures["opened"] = sum(1 for r in rows if cmd_status._after(r.get("created_at"), since))
        figures["closed"] = sum(1 for r in rows if r.get("state_reason") == "completed" and cmd_status._after(r.get("closed_at"), since))
    done = runner([f"repos/{slug}/commits/main/check-runs?per_page=100"])
    try:
        runs = json.loads(done.stdout)["check_runs"] if done.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        runs = None
    if runs is not None:
        figures["checks"] = [{"name": r.get("name"), "conclusion": r.get("conclusion") or r.get("status")} for r in runs]
    return figures


def board_stories(root: Path, slug: str) -> list[dict] | None:
    """The items of SLUG on the local board copy that `board sync` keeps, or None when there is no copy or no config to find it."""
    try:
        config = local_config.backlog_config(root)
        items = json.loads((gh_budget.home() / f"board-{config['projectOwner']}-{config['projectNumber']}.json").read_text(encoding="utf-8"))
        return [i for i in items if (i.get("content") or {}).get("repository", slug) == slug]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def status_count(stories: list[dict], status: str) -> int:
    return sum(1 for i in stories if str(i.get("status", "")).lower() == status)


def next_up(stories: list[dict]) -> str:
    """The first Ready story in priority order, as '#N title (P1)', or '' when none is Ready."""
    ready = [i for i in stories if str(i.get("status", "")).lower() == "ready"]
    if not ready:
        return ""
    first = min(ready, key=lambda i: (str(i.get("priority") or "P9"), (i.get("content") or {}).get("number") or 0))
    content = first.get("content") or {}
    tag = f" ({first['priority']})" if first.get("priority") else ""
    return f"#{content.get('number')} {content.get('title', '')}{tag}"


def latest_decision() -> dict | None:
    """The newest owner decision in relays.jsonl, or None when none is recorded or the file cannot be read."""
    try:
        found = relay.records()
    except OSError:
        return None
    return found[-1] if found else None

def needs() -> list[dict]:
    """The open owner-queue steps."""
    try:
        cmd_owner.retire_removed()
        return cmd_owner.open_items()
    except (OSError, ValueError, KeyError):
        return []


def gather(slug: str, now: datetime, steps: list[dict], log: list[dict] | None, claims: dict, alive: bool, holder: dict | None,
           stories: list[dict] | None, github: dict | None, decision: dict | None = None) -> dict:
    """The page's figures from local files. A figure that was not read is None, and none is guessed."""
    stamp = now.timestamp()
    building, warnings = cmd_status.building_block(stamp, claims, log, alive, None, holder) if log is not None else (["Building: unknown, because the run log could not be read."], [])
    busy = bool(claims) and alive
    working_list = working(claims, log or [], stamp) if busy else []
    cards = builder_cards(working_list, stories)
    return {"slug": slug, "now": now, "steps": steps, "building": building, "warnings": warnings, "busy": busy, "builders": len(claims) if busy else 0,
            "working": working_list, "pid": (holder or {}).get("pid"), "cards": cards, "landed": cmd_status.landed_today(log, stamp) if log is not None else None,
            "ready": None if stories is None else status_count(stories, "ready"), "backlog": None if stories is None else status_count(stories, "backlog"),
            "next": next_up(stories or []), "decision": decision, "github": github, "log": log, "until": gh_budget.blocked_until("")}


def stage_phrase(facts: dict) -> str:
    """'is validating' for a story at a stage, or 'is on round 2' for a builder on a later round (States.dc.html, Running)."""
    if facts["stage"] == "building" and (facts["round"] or 0) > 1:
        return f"is on round {facts['round']}"
    return f"is {facts['stage']}"


def running(working_list: list, n: int) -> str:
    """The band's sentence while builders work: each story and its stage for one or two builders, and the count for more."""
    if not 0 < len(working_list) <= 2:
        return f"{n} builder{' is' if n == 1 else 's are'} working. The stories are listed under Building now."
    told = ", and ".join(f"#{key.rsplit('#', 1)[-1]} {stage_phrase(facts)}" for key, _, facts in working_list)
    return f"{'One builder is' if len(working_list) == 1 else 'Two builders are'} working. {told}."


def state(data: dict) -> tuple[str, str, str]:
    """(css, word, sentence) for the band: waiting on GitHub, stopped, running, idle with work Ready or idle with nothing Ready."""
    if data["until"]:
        return "wait", "Waiting", f"GitHub's hourly budget is used up, so the drain is paused until about {local_config.local_time(data['until'])} and will carry on by itself."
    if data["warnings"]:
        return "fail", "Stopped", data["warnings"][0].removeprefix("Warning: ")
    n = data["builders"]
    if data["busy"]:
        return "run", "Building", running(data["working"], n)
    ready = data["ready"]
    if ready:
        return "idle", "Idle", f"No drain is running. {ready} {'story is' if ready == 1 else 'stories are'} Ready, so starting the drain would take them in priority order."
    if ready is None:
        return "idle", "Idle", "No drain is running. The Ready count is not recorded, because the board copy was not read."
    return "idle", "Idle", "No drain is running, and no story is Ready. The drain has nothing to take until a story is marked Ready."


def ago(stamp, now: datetime) -> str:
    """How long before NOW a step was queued, read from its ISO stamp, or a note that the stamp is not recorded."""
    try:
        seconds = int((now - datetime.fromisoformat(str(stamp))).total_seconds())
    except (TypeError, ValueError):
        return "age not recorded"
    if seconds < 3600:
        return f"{max(0, seconds // 60)} min ago"
    return f"{seconds // 3600} h ago" if seconds < 86400 else f"{seconds // 86400} days ago"


def step_line(item: dict, now: datetime) -> str:
    """One owner step as the mockup's: a short title, its age and source, one plain sentence on what it means, and its action as a button or a copy button."""
    source = "from an agent session" if item.get("session") else "source not recorded"
    tab = str(item.get("tab") or "")
    action = (f'<div class="acts"><button class="btn b-ghost" data-copy="{html.escape(str(item["command"]), quote=True)}">Copy command</button></div>'
              if item.get("command") else (
        f'<div class="acts"><a class="btn b-ghost" href="{html.escape(tab, quote=True)}">Open</a></div>' if tab.startswith(("http://", "https://")) else ""))
    return (f'<div class="step"><h3>{esc(item.get("step"))}</h3><p class="date">{esc(ago(item.get("created"), now))} · {source}</p>'
            f'<p class="small">{esc(cmd_owner.plain(item))}</p>{action}</div>')


def decision_block(rec: dict | None) -> str:
    """The mockup's Your latest decision line: the owner's words and the date, or nothing when none is recorded."""
    if not rec:
        return ""
    words = " ".join(str(rec.get("words") or rec.get("decision") or "not recorded").split())
    words = words if len(words) <= 300 else words[:297] + "..."
    try:
        when = local_config.local_time(datetime.fromisoformat(str(rec["created"])), "%-d %b, %H:%M %Z")
    except (KeyError, TypeError, ValueError):
        when = "date not recorded"
    return (f'<div style="display:flex;flex-direction:column;gap:4px;padding-top:12px;box-shadow:0 -1px 0 var(--line)">'
            f'<span class="small">Your latest decision</span><p>"{esc(words)}"</p><span class="date">{when}</span></div>')


def fold(rows: list[str], label: str) -> str:
    """ROWS after the first SHOWN sit behind a See all control (see city_delivery.fold)."""
    return city_delivery.fold(rows, label, SHOWN)


def needs_card(data: dict) -> str:
    steps, now = data["steps"], data["now"]
    count = f'<span class="pill p-warn">{len(steps)} step{"" if len(steps) == 1 else "s"}</span>' if steps else ""
    body = fold([step_line(s, now) for s in steps], "steps") if steps else '<p>Nothing waits on you.</p>'
    return f'<div class="card" id="needs"><div class="railhead"><h2>Needs you</h2>{count}</div>{body}{decision_block(data["decision"])}</div>'


def track(place: int) -> str:
    """The five-stage track: the stages before the current one are done, and the current one is marked."""
    items = "".join(f'<li class="{"done" if i < place else "now" if i == place else ""}">{label}</li>' for i, label in enumerate(STAGE_LABELS))
    return f'<ol class="track" aria-label="Stage {place + 1} of 5, {STAGE_LABELS[place]}">{items}</ol>'


def builder_card(key: str, mine: dict, item: dict | None, facts: dict) -> str:
    """One working builder: its number, title, size and priority, the five-stage track, its times, model and route, its round and why, its cost against
    the size's limit from COST_CEILING, and its tokens written to and read from cache. A figure the files do not hold says so."""
    n = key.rsplit("#", 1)[-1]
    title = ((item or {}).get("content") or {}).get("title") or "Title not recorded, because the board copy was not read."
    size, priority = (item or {}).get("size") or facts["size"], (item or {}).get("priority")
    tags = f'<span class="tag">{esc(size)}</span>' if size else '<span class="tag">size not recorded</span>'
    tags += f'<span class="tag">{esc(priority)}</span>' if priority else '<span class="tag">priority not recorded</span>'
    limit, spent = agent_loop.COST_CEILING.get(size), facts["cost"]
    if limit:
        cost = (f'${spent:.2f} of the ${limit:.2f} {esc(size)} limit, review included'
                f'<div class="meter"><span style="width:{min(100, round(100 * spent / limit))}%"></span></div>')
    else:
        cost = f"${spent:.2f}, with no limit set for size {esc(size)}" if size else f"${spent:.2f}, size not recorded"
    if facts["model"]:
        model = f"{facts['model'].title()}" + (f", round {facts['round']}" if facts["round"] else "") + (f". Chosen because {facts['route']}." if facts["route"] else ".")
    else:
        model = "Not recorded yet, because no round has run."
    why = f"Round {facts['round']}. {facts['why']}" if facts["why"] else "Not recorded yet."
    time = f"{facts['in_stage']} in {STAGE_LABELS[facts['place']].lower()}, {facts['in_all']} in all"
    tokens = f"{facts['written']:,} written to cache, {facts['read']:,} read from cache"
    return (f'<div class="bld" data-story="{esc(n)}"><div class="bhead"><div><span class="n">#{esc(n)}</span><p class="btitle">{esc(title)}</p></div><div class="tags">{tags}</div></div>'
            f'{track(facts["place"])}<dl class="kv"><dt>Time</dt><dd>{esc(time)}</dd><dt>Model</dt><dd>{esc(model)}</dd><dt>Round</dt><dd>{esc(why)}</dd>'
            f'<dt>Cost</dt><dd>{cost}</dd><dt>Tokens</dt><dd>{esc(tokens)}</dd></dl></div>')


def working(claims: dict, log: list[dict], now: float) -> list[tuple[str, dict, dict]]:
    """Each claimed builder as (key, claim, facts), in claim order, its facts read from the run log since its claim."""
    return [(key, mine, cmd_status.builder_facts(key.rsplit("#", 1)[-1], float(mine.get("at", 0)), log, now)) for key, mine in sorted(claims.items())]


def builder_cards(working_list: list[tuple[str, dict, dict]], stories: list[dict] | None) -> list[str]:
    """One card per working builder, in claim order, with its board card when the board copy was read."""
    by_number = {str((i.get("content") or {}).get("number")): i for i in stories or []}
    return [builder_card(key, mine, by_number.get(key.rsplit("#", 1)[-1]), facts) for key, mine, facts in working_list]


def queue_line(data: dict) -> str:
    """The queue: the next Ready story and the Ready and Backlog counts from the board copy, or a note that it was not read."""
    if data["ready"] is None:
        return '<p class="small">Queue: not recorded, because the board copy was not read.</p>'
    up = f"Next: {esc(data['next'])}." if data["next"] else "Next: no story is Ready."
    backlog = "not recorded" if data["backlog"] is None else data["backlog"]
    return f'<p>{up}</p><p class="small">{data["ready"]} Ready and {backlog} in Backlog.</p>'


def building_card(data: dict) -> str:
    """The Live card: the state band, then a block for each working builder, the queue and the drain command."""
    css, word, sentence = state(data)
    body = "".join(data["cards"]) if data["cards"] else "".join(f'<p class="small">{esc(line)}</p>' for line in data["building"])
    warned = "".join(f'<p class="small">{esc(line)}</p>' for line in data["warnings"])
    start = command("olivercode drain REPO", "Start the drain") if css == "idle" else ""
    if css == "run" and data["pid"]:  # kill releases the claim and the run lock, and the story goes back to Ready (cmd_status.stall_line) (#1381)
        start = command(f"kill {data['pid']}", "Stop the drain")
    return (f'<div class="card"><div class="railhead"><h2>Live</h2><span class="small">{local_config.local_time(data["now"], "%-d %b, %H:%M %Z")}</span></div>'
            f'<div class="band"><span class="pill p-{css}"><i></i>{word}</span><p>{esc(sentence)}</p></div>{body}{warned}{queue_line(data)}{start}</div>')


def landed_week(log: list[dict], stamp: float) -> int:
    """Stories landed in the last DAYS days, read from the run log's landed rows."""
    return sum(1 for f in cmd_status.landings(log) if f["at"] >= stamp - cmd_status.DAYS * city_delivery.DAY)


def landed_costs(log: list[dict]) -> list[float]:
    """The cost of each landed story whose cost is recorded."""
    return [float(s["cost"]) for s in city_cost.landed_stories(log) if s["cost"]]


def checks_line(github: dict | None) -> str:
    """The Health sentence for the Today paragraph: the checks on main, read by `--fetch`."""
    runs = (github or {}).get("checks")
    if runs is None:
        return "Health: checks on main are not recorded yet."
    if not runs:
        return "Health: no check is recorded on main."
    failed = [r for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral")]
    return f"Health: {len(failed)} of {len(runs)} checks on main fail." if failed else f"Health: all {len(runs)} checks on main pass."


def answer(question: str, word: str, evidence: str) -> str:
    return f'<div class="ans"><span class="q">{esc(question)}</span><span class="a">{esc(word)}</span><span class="e">{esc(evidence)}</span></div>'


def answers(data: dict) -> str:
    """The four answers, each a one-word answer and one line of evidence. A figure the files do not hold is Unknown, and a single day of data is shown as a figure, never a trend."""
    log, steps, stamp = data["log"], data["steps"], data["now"].timestamp()
    css, _, sentence = state(data)
    working = {"fail": ("No", sentence), "wait": ("Paused", sentence), "run": ("Yes", sentence)}.get(css, ("Idle", sentence))
    if log is None:
        shipping = ("Unknown", "Landed: unknown, because the run log could not be read.")
        worth = ("Unknown", "Cost is not recorded, because the run log could not be read.")
    else:
        week = landed_week(log, stamp)
        shipping = ("Yes" if week else "No", f"{len(data['landed'] or [])} landed today and {week} in the last {cmd_status.DAYS} days.")
        costs = landed_costs(log)
        if costs:
            average, limit = sum(costs) / len(costs), agent_loop.COST_CEILING["M"]
            worth = ("Yes" if average <= limit else "No", f"{money(average)} a landed story against the {money(limit)} M limit, {money(sum(costs))} in all.")
        else:
            worth = ("Unknown", "No landed story has a cost recorded.")
    needs = ("Yes", f"{len(steps)} {'step' if len(steps) == 1 else 'steps'} waiting under Needs you.") if steps else ("No", "Nothing waits on you.")
    return "".join(answer(q, *a) for q, a in (("Is it working?", working), ("Is it shipping?", shipping), ("Is it worth the cost?", worth), ("Does it need me?", needs)))


def lede(data: dict) -> str:
    """The date, a one-line headline and a short paragraph, all built from the Delivery, Cost and Health figures, then the four answers."""
    log, landed, now = data["log"], data["landed"] or [], data["now"]
    if log is None:
        headline = "The run log could not be read, so the figures are unknown."
        parts = ["Delivery and Cost are unknown, because the run log could not be read."]
    else:
        spent = sum(r["cost"] or 0 for r in landed)
        paid = f" for {money(spent)}" if spent or not landed else ""  # a day of unpriced landings names no figure (#1533)
        headline = f"{len(landed)} landed today{paid}, and {len(data['steps'])} waiting on you."
        parts = [f"Delivery: {landed_week(log, now.timestamp())} landed in the last {cmd_status.DAYS} days."]
        costs, share = landed_costs(log), city_cost.token_kinds(city_cost.rounds(log))[1]
        cost = f"Cost: {money(sum(costs) / len(costs))} a landed story" if costs else "Cost: no landed story has a cost recorded"
        parts.append(cost + (f", and {share:.1f}% of tokens were read from cache." if share is not None else "."))
    parts.append(checks_line(data["github"]))
    return (f'<section class="lede" id="today" aria-labelledby="t1"><p class="small">{esc(now.strftime("%A"))} {now.day} {esc(now.strftime("%B %Y"))}</p>'
            f'<h1 id="t1">{esc(headline)}</h1><p class="read">{esc(" ".join(parts))}</p><div class="answers">{answers(data)}</div></section>')


def today(data: dict) -> str:
    return lede(data)


def render(data: dict) -> str:
    """The whole page as one HTML string, in the mockup's markup and classes (docs/city/Main.dc.html)."""
    css, word, _ = state(data)
    now, steps = data["now"], data["steps"]
    chips = f'<a class="chipl" href="#live">{data["builders"]} builder{"" if data["builders"] == 1 else "s"}</a>' + (f'<a class="chipl warn" href="#needs">{len(steps)} need you</a>' if steps else "")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="60"><title>OliverCode City</title>{FONTS}'
            f'<style>{STYLE}</style></head><body data-written="{int(now.timestamp())}"><div class="city"><header class="bar"><div class="wrap barin">'
            '<span class="brand">OliverCode City</span><nav class="nav" aria-label="Sections"><a class="on" href="#today">Today</a><a href="#delivery">Delivery</a>'
            '<a href="#cost">Cost</a><a href="#health">Health</a></nav>'
            f'<div class="status" aria-label="System status"><span class="pill p-{css}"><i></i>{word}</span>{chips}'
            f'<span class="upd"><span class="dot" aria-hidden="true"></span>Updated {local_config.local_time(now)}</span><button class="btn b-ghost" id="refresh">Refresh</button></div></div></header>'
            '<div class="wrap"><div class="band" id="stale" hidden style="margin-top:16px"><span class="pill p-warn"><i></i>Out of date</span><p></p>'
            f'{command("olivercode status page")}</div></div>'
            f'<div class="wrap body"><aside class="rail" id="live" aria-label="Live status">{building_card(data)}{needs_card(data)}</aside>'
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
        failure_log.write_private(github_path(), json.dumps(figures))
    github = saved_github()
    github = github if github and github.get("slug") == slug else None
    try:
        log = cmd_status.run_log()
    except (OSError, ValueError):
        log = None
    stamp = now.timestamp()
    data = gather(slug, now, waiting(), log, cmd_status.live_claims(stamp), cmd_status.runner_alive(), run_lock.active(slug, stamp), board_stories(root, slug),
                  github, latest_decision())
    failure_log.write_private(page_path(), render(data))
    out(f"City written to {page_path()}.")
    return 1 if unread else 0


def enabled() -> bool:
    """Whether the owner has turned City on: `city` is true in olivercode.local.json. Off by default until the epic's last story."""
    return bool(local_config.setting("city"))


def refresh(root: Path | None = None) -> int:
    """Rewrite the page from local files, quietly. The drain calls it."""
    if not enabled():
        return 0
    root = root or Path.cwd()
    return write(repo_state.origin(root), root, out=lambda text: None)


def command_page(argv: list[str]) -> int:
    if not enabled():
        print('City is off. Turn it on by setting "city": true in olivercode.local.json.')
        return 0
    root, fetch, opening = Path.cwd(), False, False
    args = list(argv)
    if "--fetch" in args:
        args.remove("--fetch")
        fetch = True
    if "--open" in args:
        args.remove("--open")
        opening = True
    if args[:1] == ["--root"] and len(args) == 2:
        root = Path(args[1]).expanduser()
    elif args:
        print(USAGE)
        return 1
    code = write(repo_state.origin(root), root, fetch=fetch)
    if opening and page_path().exists():
        webbrowser.open(page_path().as_uri())
    return code
