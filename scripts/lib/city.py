"""City v2 (#1356): the page's frame, drawn only from local files, with no GitHub call and no model call.

`olivercode status page [--fetch] [--open] [--root DIR]` writes `city.html` to the OliverCode home, and --open shows it in the default browser. Every write reads the run log, the owner queue, the board copy
that `board sync` keeps and `city-github.json`. Only `--fetch` calls GitHub: it reads the opened and closed counts and the check results once and saves them
to `city-github.json` with the time read. The frame is a nav (Today, Delivery, Cost, Health) and a status band that gives the run state, the builder count,
the needs-you count, the Updated time, an Open on phone link when `cityArtifact` is set (#1362) and a Refresh control. The page reloads itself every 60 seconds. The Delivery, Cost and Health sections each render in
their own module. The Live rail shows a card for each working builder, the queue, and Needs you with the latest owner decision (#1357). The Today section opens with the date, a headline, a paragraph and four answers (#1361).
"""

from __future__ import annotations

import html
import json
import re
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import agent_loop, city_cost, city_delivery, city_health, cmd_owner, cmd_status, failure_log, gh_budget, local_config, relay, repo_state, run_lock

USAGE = "Usage: olivercode status page [--fetch] [--open] [--root DIR]"
STALE_SECONDS = 600
SHOWN = 5  # owner-queue steps the page lists before it says how many more
STAGE_LABELS = ("Claimed", "Building", "Validating", "Landing", "Landed")  # the builder card's track, in the order cmd_status.STAGES names them

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
background:var(--card);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line);cursor:pointer;text-decoration:none}
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
.read{font-size:17px;max-width:70ch}
.answers{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:16px;padding-top:8px}
.ans{display:flex;flex-direction:column;gap:6px;padding-top:14px;box-shadow:0 -2px 0 var(--ink)}
.ans .q{font-size:14px;color:var(--muted)}.ans .a{font-family:Newsreader,Georgia,serif;font-size:28px;line-height:1.15}.ans .e{font-size:14px;color:var(--muted)}
.bhead{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.tag{font-size:12px;font-weight:500;padding:2px 8px;border-radius:999px;background:var(--idlebg);color:var(--ink);white-space:nowrap}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;margin:0;font-size:14px}.kv dt{color:var(--muted)}.kv dd{margin:0}
.track{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));font-size:12px;color:var(--muted)}
.track li{position:relative;padding-top:20px;text-align:center}
.track li::before{content:"";position:absolute;top:3px;left:50%;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:#DDDCE3;z-index:1}
.track li::after{content:"";position:absolute;top:8px;right:50%;width:100%;height:2px;background:#DDDCE3}
.track li:first-child::after{display:none}
.track li.done::before,.track li.done::after,.track li.now::after{background:var(--ink)}
.track li.now::before{background:var(--accent);box-shadow:0 0 0 4px var(--asoft)}
.track li.now{color:var(--accent);font-weight:500}
.meter{height:6px;border-radius:999px;background:var(--idlebg);overflow:hidden;margin-top:4px}.meter span{display:block;height:100%;background:var(--ink)}
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
    """The one GitHub read: opened and closed counts over the last week and the check results on main (CI runs on main only, #1354). A figure that could not be read is None."""
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
    """The first Ready story in priority order, as '#N title (P1)', or '' when none is Ready (#1357)."""
    ready = [i for i in stories if str(i.get("status", "")).lower() == "ready"]
    if not ready:
        return ""
    first = min(ready, key=lambda i: (str(i.get("priority") or "P9"), (i.get("content") or {}).get("number") or 0))
    content = first.get("content") or {}
    tag = f" ({first['priority']})" if first.get("priority") else ""
    return f"#{content.get('number')} {content.get('title', '')}{tag}"


def latest_decision() -> dict | None:
    """The newest owner decision in relays.jsonl, or None when none is recorded or the file cannot be read (#1357)."""
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
    cards = builder_cards(claims, stories, log, stamp) if busy else []
    return {"slug": slug, "now": now, "steps": steps, "building": building, "warnings": warnings, "busy": busy, "builders": len(claims) if busy else 0,
            "cards": cards, "landed": cmd_status.landed_today(log, stamp) if log is not None else None,
            "ready": None if stories is None else status_count(stories, "ready"), "backlog": None if stories is None else status_count(stories, "backlog"),
            "next": next_up(stories or []), "decision": decision, "github": github, "log": log, "until": gh_budget.blocked_until(""),
            "artifact": str(local_config.setting("cityArtifact") or "")}


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


def ago(stamp, now: datetime) -> str:
    """How long before NOW a step was queued, read from its ISO stamp, or a note that the stamp is not recorded (#1357)."""
    try:
        seconds = int((now - datetime.fromisoformat(str(stamp))).total_seconds())
    except (TypeError, ValueError):
        return "age not recorded"
    if seconds < 3600:
        return f"{max(0, seconds // 60)} min ago"
    return f"{seconds // 3600} h ago" if seconds < 86400 else f"{seconds // 86400} days ago"


def step_line(item: dict, now: datetime) -> str:
    """One owner step: its number and text, its age and session, and the command tried with its error, as a copyable command (#1357)."""
    source = f"from {esc(item['session'])}" if item.get("session") else "source not recorded"
    error = f'<p class="small">The error: {esc(item["error"])}</p>' if item.get("error") else ""
    action = command(item["command"]) if item.get("command") else ""
    return (f'<div class="step"><h3>#{esc(item.get("id"))} {esc(item.get("step"))}</h3><p class="date">{esc(ago(item.get("created"), now))} · {source}</p>'
            f'{error}{action}</div>')


def decision_block(rec: dict | None) -> str:
    """The latest owner decision with its date and the owner's words, or nothing when none is recorded (#1357)."""
    if not rec:
        return ""
    words = " ".join(str(rec.get("words") or "").split())
    words = words if len(words) <= 300 else words[:297] + "..."
    return (f'<div class="step"><h3>Latest decision: {esc(rec.get("decision") or "not recorded")}</h3>'
            f'<p class="date">{esc(str(rec.get("created", ""))[:10])} · chose {esc(rec.get("choice") or "not recorded")}</p>'
            f'<p class="small">Your words: {esc(words)}</p></div>')


def needs_card(data: dict) -> str:
    steps, now = data["steps"], data["now"]
    lines = "".join(step_line(s, now) for s in steps[:SHOWN])
    more = f'<p class="small">and {len(steps) - SHOWN} more. See them with `olivercode owner`.</p>' if len(steps) > SHOWN else ""
    count = f'<span class="cnt">{len(steps)}</span>' if steps else ""
    body = lines + more if steps else '<p>Nothing waits on you.</p>'
    return f'<div class="card" id="needs"><div class="head"><h2>Needs you</h2>{count}</div>{body}{decision_block(data["decision"])}</div>'


def track(place: int) -> str:
    """The five-stage track: the stages before the current one are done, and the current one is marked."""
    items = "".join(f'<li class="{"done" if i < place else "now" if i == place else ""}">{label}</li>' for i, label in enumerate(STAGE_LABELS))
    return f'<ol class="track" aria-label="Stage {place + 1} of 5, {STAGE_LABELS[place]}">{items}</ol>'


def builder_card(key: str, mine: dict, item: dict | None, facts: dict) -> str:
    """One working builder: its number, title, size and priority, the five-stage track, its times, model and route, its round and why, its cost against
    the size's limit from COST_CEILING, and its tokens written to and read from cache. A figure the files do not hold says so (#1357)."""
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
    return (f'<div class="step" data-story="{esc(n)}"><div class="bhead"><div><h3>#{esc(n)}</h3><p>{esc(title)}</p></div><div>{tags}</div></div>'
            f'{track(facts["place"])}<dl class="kv"><dt>Time</dt><dd>{esc(time)}</dd><dt>Model</dt><dd>{esc(model)}</dd><dt>Round</dt><dd>{esc(why)}</dd>'
            f'<dt>Cost</dt><dd>{cost}</dd><dt>Tokens</dt><dd>{esc(tokens)}</dd></dl></div>')


def builder_cards(claims: dict, stories: list[dict] | None, log: list[dict] | None, now: float) -> list[str]:
    """One card per working builder, in claim order, with its board card when the board copy was read."""
    by_number = {str((i.get("content") or {}).get("number")): i for i in stories or []}
    cards = []
    for key, mine in sorted(claims.items()):
        n = key.rsplit("#", 1)[-1]
        facts = cmd_status.builder_facts(n, float(mine.get("at", 0)), log or [], now)
        cards.append(builder_card(key, mine, by_number.get(n), facts))
    return cards


def queue_line(data: dict) -> str:
    """The queue: the next Ready story and the Ready and Backlog counts from the board copy, or a note that it was not read (#1357)."""
    if data["ready"] is None:
        return '<p class="small">Queue: not recorded, because the board copy was not read.</p>'
    up = f"Next: {esc(data['next'])}." if data["next"] else "Next: no story is Ready."
    backlog = "not recorded" if data["backlog"] is None else data["backlog"]
    return f'<p>{up}</p><p class="small">{data["ready"]} Ready and {backlog} in Backlog.</p>'


def building_card(data: dict) -> str:
    body = "".join(data["cards"]) if data["cards"] else "".join(f'<div class="step"><p>{esc(line)}</p></div>' for line in data["building"])
    warned = "".join(f'<div class="step"><p>{esc(line)}</p></div>' for line in data["warnings"])
    return (f'<div class="card" id="live"><h2>Building now</h2>{body}{warned}{queue_line(data)}'
            f'{command("olivercode drain REPO")}</div>')


def money(value: float) -> str:
    return f"${value:,.2f}"


def landed_week(log: list[dict], stamp: float) -> int:
    """Stories landed in the last DAYS days, read from the run log's landed rows (#1361)."""
    return sum(1 for f in cmd_status.landings(log) if f["at"] >= stamp - cmd_status.DAYS * city_delivery.DAY)


def landed_costs(log: list[dict]) -> list[float]:
    """The cost of each landed story whose cost is recorded (#1361)."""
    return [float(s["cost"]) for s in city_cost.landed_stories(log) if s["cost"]]


def checks_line(github: dict | None) -> str:
    """The Health sentence for the Today paragraph: the checks on main, read by `--fetch` (#1361)."""
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
    """The four answers, each a one-word answer and one line of evidence. A figure the files do not hold is Unknown, and a single day of data is shown as a figure, never a trend (#1361)."""
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
    """The date, a one-line headline and a short paragraph, all built from the Delivery, Cost and Health figures, then the four answers (#1361)."""
    log, landed, now = data["log"], data["landed"] or [], data["now"]
    if log is None:
        headline = "The run log could not be read, so the figures are unknown."
        parts = ["Delivery and Cost are unknown, because the run log could not be read."]
    else:
        spent = sum(r["cost"] or 0 for r in landed)
        headline = f"{len(landed)} landed today for {money(spent)}, and {len(data['steps'])} waiting on you."
        parts = [f"Delivery: {landed_week(log, now.timestamp())} landed in the last {cmd_status.DAYS} days."]
        costs, share = landed_costs(log), city_cost.token_kinds(city_cost.rounds(log))[1]
        cost = f"Cost: {money(sum(costs) / len(costs))} a landed story" if costs else "Cost: no landed story has a cost recorded"
        parts.append(cost + (f", and {share:.1f}% of tokens were read from cache." if share is not None else "."))
    parts.append(checks_line(data["github"]))
    return (f'<p class="small">{esc(now.strftime("%A"))} {now.day} {esc(now.strftime("%B %Y"))}</p><h2>{esc(headline)}</h2>'
            f'<p class="read">{esc(" ".join(parts))}</p><div class="answers">{answers(data)}</div>')


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
    return (f'<section class="chap" id="today" aria-label="Today">{lede(data)}<div class="card"><h3>Landed today</h3>{"".join(f"<p>{esc(r)}</p>" for r in rows)}{total}</div>'
            f'<div class="card"><h3>Pace</h3><p>{esc(pace)}</p><p class="small">{esc(read)}</p></div></section>')


def render(data: dict) -> str:
    """The whole page as one HTML string."""
    css, word, sentence = state(data)
    now, steps = data["now"], data["steps"]
    chips = f'<span>{data["builders"]} builder{"" if data["builders"] == 1 else "s"}</span>' + (f'<a href="#needs">{len(steps)} need you</a>' if steps else "")
    start = command("olivercode drain REPO") if css == "idle" else ""
    phone = f'<a class="btn" href="{html.escape(data["artifact"], quote=True)}">Open on phone</a>' if data.get("artifact") else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="refresh" content="60"><title>OliverCode City</title>'
            f'<style>{STYLE}</style></head><body data-written="{int(now.timestamp())}"><div class="city"><header class="bar"><div class="wrap barin">'
            '<span class="brand">OliverCode City</span><nav class="nav" aria-label="Sections"><a href="#today">Today</a><a href="#delivery">Delivery</a>'
            '<a href="#cost">Cost</a><a href="#health">Health</a></nav>'
            f'<div class="status" aria-label="System status"><span class="pill c-{css}"><i></i>{word}</span>{chips}<span>Updated {now:%H:%M} UTC</span>'
            f'{phone}<button class="btn" id="refresh">Refresh</button></div></div></header>'
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
    data = gather(slug, now, waiting(), log, cmd_status.live_claims(stamp), cmd_status.runner_alive(), run_lock.active(slug, stamp), board_stories(root, slug),
                  github, latest_decision())
    failure_log.write_atomic(page_path(), render(data))
    out(f"City written to {page_path()}.")
    return 1 if unread else 0


def enabled() -> bool:
    """Whether the owner has turned City on: `city` is true in olivercode.local.json. Off by default until the epic's last story (#1378)."""
    return bool(local_config.setting("city"))


def refresh(root: Path | None = None) -> int:
    """Rewrite the page from local files, quietly. The drain calls it (#1350)."""
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
