"""The one plain-language layer behind `olivercode status` and City (#1177).

`snapshot(...)` gathers the figures once. `text(snap)` prints them as a short briefing for the terminal, and `dashboard_html(snap)` draws the same
figures as cards, bars and status marks for City. Both say what happened, why it matters and what to do, and use no engineering words. The raw
steps stay one command away (`olivercode owner show N`). The module reads its arguments and calls nothing.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

RULE = "─" * 40
CD_TARGET = "~/.claude/olivercode"  # the documented path, so the owner can paste the two commands from City

# (group, what it is, pattern on the step text). The first match wins.
ATTENTION = (
    ("Stories to split", "ran out of turns and need splitting", r"parked on the turn limit|oversized"),
    ("Approvals", "need your approval before work can move", r"approve"),
    ("Failed checks", "did not pass their checks", r"validation failed|suite failed|level with origin|tests? fail"),
    ("Cleanup", "need tidying", r"branch|worktree|tidy|out of place|placement|older than origin"),
    ("Setup", "need a fix to your setup", r"python|path|sleep|budget|synced|gate command|does not exist|no repo at"),
)
# (area, headline, what it means, what to do, pattern on the step text)
SETUP = (
    ("Project locations", "Some project folders are in the wrong place", "Hooks can be out of date there.", "Run `olivercode place`.", r"out of place|placement|older than origin"),
    ("Validation", "A fresh install's tests did not pass", "A new installation may have problems.", "Run `olivercode health` for the list.", r"suite failed"),
    ("Context", "Claude starts with more context than planned", "Sessions begin heavier than they need to.", "Trim the always-loaded files.", r"budget|words"),
    ("Background work", "Your Mac goes to sleep", "Sleep can stop unattended work while you are away.", "Change the sleep settings.", r"sleep"),
    ("Projects", "Some projects are behind GitHub", "Their changes have not reached GitHub yet.", "Run `olivercode fleet-sync`.", r"level with origin|origin lacks|no repo at"),
    ("Installation", "Your install needs a fix", "OliverCode may not be found in a new terminal.", "Run `olivercode install`.", r"python|\bPATH\b|synced"),
)
AREAS = ("Installation", "Projects", "Project locations", "Validation", "Background work", "Context")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _money(value) -> str:
    return "not recorded" if value is None else f"${value:.2f}"


def _millions(tokens) -> str:
    return "not recorded" if tokens is None else (f"{tokens / 1e6:.1f}M" if tokens >= 1_000_000 else f"{tokens:,}")


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


def group_of(step: str) -> str:
    for name, _, pattern in ATTENTION:
        if re.search(pattern, step, re.IGNORECASE):
            return name
    return "Other"


def attention(steps: list[dict]) -> list[dict]:
    """The open owner steps grouped by what the owner would do, biggest group last so decisions lead: [{name, means, steps}]."""
    order = [name for name, _, _ in ATTENTION] + ["Other"]
    means = {name: m for name, m, _ in ATTENTION} | {"Other": "need a look"}
    found: dict[str, list[dict]] = {}
    for item in steps:
        found.setdefault(group_of(str(item.get("step", ""))), []).append(item)
    return [{"name": n, "means": means[n], "steps": found[n]} for n in order if n in found]


def setup_items(steps: list[dict]) -> list[dict]:
    """The setup problems the maintain steps name, one per area, as {area, headline, meaning, fix, count}."""
    found: dict[str, dict] = {}
    for item in steps:
        text = str(item.get("step", ""))
        if item.get("session") != "maintain" and "level with origin" not in text:
            continue
        for area, headline, meaning, fix, pattern in SETUP:
            if re.search(pattern, text, re.IGNORECASE):
                row = found.setdefault(area, {"area": area, "headline": headline, "meaning": meaning, "fix": fix, "count": 0})
                row["count"] += 1
                break
    return list(found.values())


def week(rows: list[dict], now: datetime, days: int = 7) -> list[dict]:
    """[{day, opened, closed}] for the last `days` days, oldest first, from the issue rows' created and closed times."""
    def on(stamp, day):
        return bool(stamp) and datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(now.tzinfo).date() == day
    out = []
    for back in range(days - 1, -1, -1):
        day = (now - timedelta(days=back)).date()
        out.append({"day": day.strftime("%a"), "opened": sum(on(r.get("created_at"), day) for r in rows), "closed": sum(on(r.get("closed_at"), day) for r in rows)})
    return out


def trend(opened: int, closed: int, open_now: int, days: int = 7) -> tuple[str, str]:
    """(headline, detail) for the backlog's direction, hedged because the queue changes constantly."""
    if open_now == 0:
        return "The backlog is empty.", "Everything that was filed has been delivered."
    net = (closed - opened) / days
    if abs(closed - opened) <= max(2, 0.02 * max(closed, opened)):
        return "You are keeping up with new work.", f"{closed} stories were delivered and {opened} were added this week."
    if closed > opened:
        return "The backlog is shrinking.", f"About {net:.1f} fewer open stories a day at this pace. Treat any finish date as a rough guess."
    return "New work is arriving faster than it is delivered.", f"{opened} were added and {closed} delivered this week."


def snapshot(*, slug: str, now: datetime, open_now: int, rows: list[dict], numbers: dict, steps: list[dict], today: list[dict], ready: str,
             runner: dict, ideas: int, city: bool, latest: dict | None) -> dict:
    """Everything the briefing shows. `today` is [{story, title, tokens, cost}] delivered today; `runner` is {building, allowed, state, load}."""
    since = now - timedelta(days=7)
    opened = sum(1 for r in rows if r.get("created_at") and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since)
    closed = sum(1 for r in rows if r.get("closed_at") and datetime.fromisoformat(r["closed_at"].replace("Z", "+00:00")) >= since)
    headline, detail = trend(opened, closed, open_now)
    priced = [t["cost"] for t in today if t.get("cost") is not None]
    return {"slug": slug, "now": now, "open": open_now, "opened": opened, "closed": closed, "days": week(rows, now), "trend": (headline, detail), "numbers": numbers,
            "groups": attention(steps), "waiting": len(steps), "setup": setup_items(steps), "today": today, "today_cost": sum(priced) if priced else None,
            "today_tokens": sum(int(t.get("tokens") or 0) for t in today), "ready": ready, "runner": runner, "ideas": ideas, "city": city, "latest": latest}


def summary_line(snap: dict) -> str:
    waiting, runner = snap["waiting"], snap["runner"]
    work = "Work is running." if runner["building"] else ("There is work ready, but nothing is running." if snap["open"] else "Nothing is waiting to be built.")
    return f"{work} {plural(waiting, 'thing')} {'needs' if waiting == 1 else 'need'} your attention." if waiting else f"{work} Nothing needs your attention."


def text(snap: dict) -> list[str]:
    """The terminal briefing: attention first, then work, today, the week, cost, ideas, setup and City."""
    runner, nums, out = snap["runner"], snap["numbers"], []
    out += [f"OliverCode · {snap['slug']}", RULE, "", "YOUR ATTENTION"]
    if snap["waiting"]:
        out.append(f"{plural(snap['waiting'], 'thing')} {'needs' if snap['waiting'] == 1 else 'need'} you.")
        out += [f"  {len(g['steps'])} {g['name'].lower()}" for g in snap["groups"]]
        out += ["", "Run `olivercode owner list` to see them."]
    else:
        out.append("Nothing needs you right now.")
    out += ["", RULE, "", "WORK", ""]
    out.append(f"  Builders  {runner['building']} running, {runner['allowed']} allowed")
    if runner.get("load"):
        out.append(f"  Machine   {runner['load']}")
    out.append(f"  Open      {plural(snap['open'], 'story', 'stories')}")
    if runner.get("run"):
        out.append(f"  Run       {runner['run']}")
    if snap["ready"]:
        out.append(f"  Next up   {snap['ready']}")
    out += [""] + [f"  {line}" for line in runner.get("lines", [])]
    out.append("Nothing is building right now. Run `olivercode drain REPO` to start the queue." if not runner["building"] and snap["open"] else "")
    out += ["", RULE, "", "DELIVERED TODAY", ""]
    if snap["today"]:
        out += [f"  {plural(len(snap['today']), 'story', 'stories')} · {snap['today_tokens']:,} tokens · {_money(snap['today_cost'])}", ""]
        out += [f"  #{t['story']}  {t['title']}" for t in snap["today"][:5]]
    else:
        out.append("  Nothing yet today.")
    out += ["", RULE, "", "THIS WEEK", "", f"  {snap['closed']} delivered   {snap['opened']} added   {snap['open']} open", "", f"  {snap['trend'][0]}", f"  {snap['trend'][1]}"]
    out += ["", RULE, "", "COST", ""]
    if nums.get("tokens_per_closed") is not None:
        out += [f"  {_money(nums['cost_per_closed'])} per finished story" if nums.get("cost_per_closed") is not None else "  Cost per story not recorded yet.", f"  {_millions(nums['tokens_per_closed'])} tokens per story"]
    else:
        out.append("  Not recorded yet.")
    out += [f"  Work moved to a fresh session {plural(nums.get('handovers', 0), 'time')}; you stepped into {plural(nums.get('threads', 0), 'thread')}."]
    if snap["ideas"]:
        out += ["", RULE, "", "IDEAS", "", f"  {snap['ideas']} waiting for review.", "  Run `olivercode candidates`."]
    if snap["setup"]:
        out += ["", RULE, "", "YOUR SETUP", ""] + [f"  ⚠ {s['headline']}" for s in snap["setup"]] + ["", "Run `olivercode health` for details."]
    if not snap["city"]:
        out += ["", RULE, "", "CITY", "", "  Not connected to Claude Desktop.", '  Say "Set up OliverCode City" to finish.']
    return out


STYLE = """
:root{--bg:#fff;--card:#fff;--ink:#17191d;--sub:#5c6470;--line:#dfe3e8;--good:#176b45;--warn:#986000;--bad:#a72d25;--accent:#5b50b8;--soft:#f3f2fa;--wash:#f7f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#101216;--card:#171a20;--ink:#f0f2f5;--sub:#a4acb8;--line:#303640;--good:#59c58c;--warn:#e5ad50;--bad:#ef8177;--accent:#aaa2ff;--soft:#25243b;--wash:#1c2027}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 22px 72px}h1{font-size:clamp(1.8rem,4vw,2.5rem);line-height:1.15;letter-spacing:-.035em;margin:0}h2{font-size:1.3rem;letter-spacing:-.02em;margin:42px 0 14px}h3{font-size:1.05rem;margin:0 0 8px}p{margin:8px 0}.sub,.label{color:var(--sub)}
.lede{max-width:68ch;font-size:1.04rem;margin:10px 0 24px}.eyebrow{font-size:.75rem;text-transform:uppercase;letter-spacing:.12em;color:var(--sub);font-weight:650;margin-bottom:8px}
.cards{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr))}.card{background:var(--card);border:1px solid var(--line);padding:18px}.big{font-size:2.15rem;font-weight:680;line-height:1.12;letter-spacing:-.04em;margin:5px 0}.label{font-size:.82rem;font-weight:600}.note{font-size:.88rem;color:var(--sub);margin-top:6px}
.pill{display:inline-block;border:1px solid var(--line);padding:2px 8px;border-radius:3px;font-size:.78rem;font-weight:650;color:var(--sub)}.pill.good{border-color:var(--good);color:var(--good)}.pill.warn{border-color:var(--warn);color:var(--warn)}.pill.bad{border-color:var(--bad);color:var(--bad)}
.section-intro{max-width:70ch;color:var(--sub);margin:-4px 0 14px}details{border-top:1px solid var(--line);padding:0}details:last-child{border-bottom:1px solid var(--line)}
summary{cursor:pointer;list-style:none;padding:14px 4px;display:flex;align-items:flex-start;gap:12px;font-weight:650}summary::-webkit-details-marker{display:none}summary:after{content:"＋";color:var(--sub);margin-left:auto;font-weight:400}details[open]>summary:after{content:"−"}summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.summary-title{flex:1;min-width:150px}.summary-meta{color:var(--sub);font-size:.88rem;font-weight:500}.expansion{padding:2px 16px 18px 16px;color:var(--ink)}.expansion p{max-width:72ch}.expansion ul{margin:8px 0 0;padding-left:22px}.expansion li{padding:4px 0}
.attention{border:1px solid var(--line);margin:0 0 8px;padding:0 12px;background:var(--card)}.attention summary{padding:13px 2px}.attention .expansion{padding:4px 2px 14px}
.row{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:12px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.row>div:first-child{flex:1}.row .sub{max-width:34ch;font-size:.9rem}
.bars{display:flex;align-items:flex-end;gap:10px;height:132px;margin:14px 0 6px}.bars>div{flex:1;min-width:0;text-align:center;font-size:.75rem;color:var(--sub);display:flex;flex-direction:column;justify-content:flex-end;height:100%}.bar{display:flex;gap:3px;align-items:flex-end;justify-content:center;flex:1}.bar i{display:block;width:42%;min-height:2px}.o{background:#aeb5bf}.c{background:var(--accent)}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.84rem;color:var(--sub)}.legend span:before{content:"";display:inline-block;width:9px;height:9px;margin-right:6px;background:#aeb5bf}.legend .delivered:before{background:var(--accent)}
.flow{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.flow>div{padding:12px;background:var(--wash);border-left:2px solid var(--line)}.flow .positive{border-color:var(--good)}.flow .negative{border-color:var(--warn)}.flow strong{display:block;font-size:1.45rem;line-height:1.25}
.meter{height:6px;background:var(--line);margin:12px 0 4px}.meter i{display:block;height:100%;background:var(--accent)}.health-list{margin-top:8px}.health-list .row{padding:14px 0}.health-list .fix{max-width:35ch;color:var(--sub);font-size:.9rem}
code{font:.9em ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--soft);padding:2px 5px}
@media(max-width:600px){main{padding:20px 15px 52px}.row{display:block}.row .sub,.row .fix{margin-top:6px;max-width:none}.flow{grid-template-columns:1fr}.bars{gap:5px}.summary-meta{width:100%}}
"""


def _card(label: str, big: str, note: str = "") -> str:
    return f'<div class="card"><div class="label">{esc(label)}</div><div class="big">{esc(big)}</div><div class="sub">{esc(note)}</div></div>'


def _bars(days: list[dict]) -> str:
    top = max([d["opened"] for d in days] + [d["closed"] for d in days] + [1])
    cols = "".join(f'<div><span class="bar"><i class="o" style="height:{d["opened"] / top * 100:.0f}%" title="{d["opened"]} added"></i>'
                   f'<i class="c" style="height:{d["closed"] / top * 100:.0f}%" title="{d["closed"]} delivered"></i></span>{esc(d["day"])}</div>' for d in days)
    return f'<div class="bars" role="img" aria-label="Stories added and delivered each day">{cols}</div><p class="sub">Grey: added. Purple: delivered.</p>'


def _attention_html(snap: dict) -> str:
    if not snap["waiting"]:
        return '<div class="card">Nothing needs you right now. The queue is clear of owner decisions.</div>'
    blocks = []
    for g in snap["groups"]:
        items = "".join(f'<li><b>#{esc(i.get("id"))}</b> {esc(str(i.get("step", "")).splitlines()[0][:160])}</li>' for i in g["steps"][:8])
        more = f'<li class="sub">And {len(g["steps"]) - 8} more in this group.</li>' if len(g["steps"]) > 8 else ""
        blocks.append(f'<details class="attention"><summary><span class="summary-title">{esc(g["name"])}</span><span class="summary-meta">{len(g["steps"])} · {esc(g["means"])}</span></summary><div class="expansion"><ul>{items}{more}</ul></div></details>')
    return f'<p class="section-intro">{plural(snap["waiting"], "decision")} or fix is holding work. Open a group to see exactly what is waiting.</p>{"".join(blocks)}<p class="note">Full list: <code>olivercode owner list</code></p>'

def _health_html(snap: dict) -> str:
    bad = {s["area"] for s in snap["setup"]}
    marks = "".join(f'<span class="pill {"warn" if a in bad else "good"}">{esc(a)} · {"needs attention" if a in bad else "clear"}</span> ' for a in AREAS)
    rows = "".join(f'<div class="row"><div><b>{esc(s["headline"])}</b><div class="sub">{esc(s["meaning"])}</div></div><div class="fix">{esc(s["fix"])}</div></div>' for s in snap["setup"])
    lead = "A few things could slow the work down. Each includes what it means and the next step." if snap["setup"] else "All six checks are clear. Nothing in the setup is flagged."
    return f'<div class="card"><p><b>{esc(lead)}</b></p><div class="cards">{marks}</div><div class="health-list">{rows}</div></div>'

def dashboard_html(snap: dict) -> str:
    """City: a narrative operating view, readable expansions and grounded comparisons."""
    runner, nums = snap["runner"], snap["numbers"]
    state = "Running" if runner["building"] else "Idle"
    pill = f'<span class="pill {"good" if runner["building"] else ""}">{state}</span>'
    latest = f'<p class="note">Latest delivery: <b>#{esc(snap["latest"]["number"])} {esc(snap["latest"]["title"])}</b></p>' if snap.get("latest") else ""
    if nums.get("tokens_per_closed") is not None:
        cost = (_money(nums.get("cost_per_closed")), f"~{_millions(nums['tokens_per_closed'])} tokens per delivered story")
    else:
        cost = ("Not recorded", "No completed stories in this window")
    load = f'<p class="note">{esc(runner["load"])}</p>' if runner.get("load") else ""
    allowed = max(int(runner["allowed"]) or 1, 1)
    meter = f'<div class="meter" aria-label="{runner["building"]} of {allowed} builder slots in use"><i style="width:{min(100, runner["building"] / allowed * 100):.0f}%"></i></div>'
    net = snap["closed"] - snap["opened"]
    net_label = "Net backlog reduction" if net > 0 else ("Net backlog growth" if net < 0 else "No net change")
    ratio = "No new work arrived" if not snap["opened"] else f'{snap["closed"] / snap["opened"]:.1f} deliveries per story added'
    pace = f'{snap["closed"] / 7:.1f} delivered/day · {snap["opened"] / 7:.1f} added/day'
    benchmark = f'To shrink the queue, delivery must exceed incoming work ({snap["opened"]} added this week; at least {snap["opened"] + 1} deliveries).' if snap["opened"] else "No new stories arrived this week; any delivery reduces the queue."
    daily = "".join(f'<li>{esc(d["day"])}: {d["closed"]} delivered · {d["opened"]} added</li>' for d in snap["days"])
    next_up = f'<p><b>Next up:</b> {esc(snap["ready"])}</p>' if snap["ready"] else ""
    return (
        f'<div class="eyebrow">OliverCode · Live operating picture</div><h1>OliverCode City</h1>'
        f'<p class="lede">{esc(summary_line(snap))} <span class="sub">Updated {esc(snap["now"].strftime("%A, %H:%M"))}.</span></p>'
        f'<div class="cards">{_card("Stories in the queue", str(snap["open"]), f"{len(snap["today"])} delivered today")}'
        f'{_card("Waiting on you", str(snap["waiting"]), "decisions, approvals or fixes")}'
        f'{_card("Cost per delivery", cost[0], cost[1])}'
        f'{_card("Delivered today", str(len(snap["today"])), f"{snap["today_tokens"]:,} tokens · {_money(snap["today_cost"])}")}</div>'
        f'<section><h2>What needs your attention</h2><p class="section-intro">Owner decisions come first. They are the work only you can unblock.</p>{_attention_html(snap)}</section>'
        f'<section><h2>Work underway</h2><div class="card"><div>{pill} <b>{runner["building"]} of {allowed} builder slots in use</b></div>{meter}{load}'
        f'<p>{esc("Nothing is building at the moment." if not runner["building"] else "Stories are moving through the runner.")}</p>{next_up}{latest}</div></section>'
        f'<section><h2>Delivery pace</h2><div class="card"><b>{esc(snap["trend"][0])}</b><p class="sub">{esc(snap["trend"][1])}</p>'
        f'{_bars(snap["days"])}<div class="legend"><span>Added</span><span class="delivered">Delivered</span></div>'
        f'<div class="flow"><div><span class="label">Delivered</span><strong>{snap["closed"]}</strong><span class="note">this week</span></div>'
        f'<div><span class="label">Added</span><strong>{snap["opened"]}</strong><span class="note">this week</span></div>'
        f'<div class="{"positive" if net >= 0 else "negative"}"><span class="label">{esc(net_label)}</span><strong>{net:+}</strong><span class="note">stories · 7 days</span></div></div>'
        f'<p class="note">{esc(pace)}. {esc(ratio)}. {esc(benchmark)}</p>'
        f'<details><summary><span class="summary-title">Daily breakdown</span><span class="summary-meta">7-day view</span></summary><div class="expansion"><ul>{daily}</ul></div></details>'
        f'<p class="note">Benchmark: deliveries need to stay ahead of incoming work to reduce backlog. This compares with your own queue, not an industry target.</p></div></section>'
        f'<section><h2>System health</h2>{_health_html(snap)}</section>'
        f'<section><h2>Keep exploring</h2><p>{plural(snap["ideas"], "idea")} waiting for review. <code>olivercode candidates</code></p>'
        f'<p class="term">Terminal view</p><p><code>cd {esc(CD_TARGET)}</code> then <code>olivercode status</code>.</p></section>'
    )
