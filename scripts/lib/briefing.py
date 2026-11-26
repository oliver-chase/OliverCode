"""The one plain-language layer behind `olivercode status` and City (#1177).

`snapshot(...)` gathers the figures once. `text(snap)` prints them as a short briefing for the terminal, and `dashboard_html(snap)` draws the same
figures as cards, bars and status marks for City. Both say what happened, why it matters and what to do, and use no engineering words. The raw
steps stay one command away (`olivercode owner show N`). The module reads its arguments and calls nothing.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from lib import local_config

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
:root{--bg:#fff;--card:#fff;--ink:#17151b;--sub:#687080;--line:#e8e6ed;--accent:#a99be8;--accent-strong:#7864c8;--lavender:#f0edff;--mint:#e5f5ed;--mint-ink:#39765b;--peach:#fff0e7;--peach-ink:#9b6546;--blue:#e9f2ff;--blue-ink:#5477a6;--yellow:#fff6dc;--yellow-ink:#92722d;--wash:#faf9fc}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 24px 76px}
h1,h2,h3,.big,.flow strong{font-family:Georgia,"Times New Roman",serif;font-weight:500}
h1{font-size:clamp(2rem,5vw,3rem);line-height:1.12;letter-spacing:-.035em;margin:0}
h2{font-size:1.55rem;letter-spacing:-.02em;margin:44px 0 14px}
h3{font-size:1.15rem;margin:0 0 8px}
p{margin:8px 0}.sub,.label,.note,.summary-meta{color:var(--sub)}
.lede{max-width:68ch;font-size:1.05rem;margin:12px 0 26px}.eyebrow{font-size:.74rem;text-transform:uppercase;letter-spacing:.13em;color:var(--sub);font-weight:650;margin-bottom:8px}
.cards{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr))}
.card{background:#fff;border:1px solid var(--line);padding:18px;border-radius:4px}
.big{font-size:2.4rem;line-height:1.12;letter-spacing:-.04em;margin:5px 0}
.label{font-size:.82rem;font-weight:650}.note{font-size:.88rem;margin-top:6px}
.pill{display:inline-block;border:1px solid var(--line);padding:3px 9px;border-radius:4px;font-size:.78rem;font-weight:650;color:var(--sub);background:#fff}
.pill.good{border-color:#c5e8d5;background:var(--mint);color:var(--mint-ink)}
.pill.warn{border-color:#f4d6bc;background:var(--peach);color:var(--peach-ink)}
.pill.bad{border-color:#edc7ce;background:#fff0f2;color:#9b5966}
.pill.info{border-color:#d6d0fa;background:var(--lavender);color:var(--accent-strong)}
.section-intro{max-width:70ch;color:var(--sub);margin:-4px 0 14px}
details{border-top:1px solid var(--line);padding:0}details:last-child{border-bottom:1px solid var(--line)}
summary{cursor:pointer;list-style:none;padding:15px 4px;display:flex;align-items:flex-start;gap:12px;font-weight:650}
summary::-webkit-details-marker{display:none}summary:after{content:"＋";color:var(--accent-strong);margin-left:auto;font-weight:400}details[open]>summary:after{content:"−"}summary:focus-visible{outline:2px solid var(--accent-strong);outline-offset:3px}
.summary-title{flex:1;min-width:150px}.summary-meta{font-size:.88rem;font-weight:500}.expansion{padding:2px 16px 18px;color:var(--ink)}.expansion p{max-width:72ch}.expansion ul{margin:8px 0 0;padding-left:22px}.expansion li{padding:5px 0}
.attention{border:1px solid var(--line);margin:0 0 9px;padding:0 12px;background:#fff;border-radius:4px}.attention summary{padding:13px 2px}.attention .expansion{padding:4px 2px 14px}
.row{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:13px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.row>div:first-child{flex:1}.row .sub{max-width:34ch;font-size:.9rem}
.bars{display:flex;align-items:stretch;gap:10px;height:160px;margin:14px 0 6px}.chart-day{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:5px;color:var(--sub);font-size:.75rem}.chart-values{display:flex;justify-content:center;gap:8px;font-size:.72rem;font-variant-numeric:tabular-nums}.bar{display:flex;gap:4px;align-items:flex-end;justify-content:center;width:100%;height:112px}.bar i{display:block;width:35%;min-height:2px}.o{background:#d9dce4}.c{background:#b7a8f1}.chart-label{padding-top:2px}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.84rem;color:var(--sub)}.legend span:before{content:"";display:inline-block;width:9px;height:9px;margin-right:6px;background:#d9dce4}.legend .delivered:before{background:#b7a8f1}
.flow{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.flow>div{padding:13px;background:var(--wash);border-left:3px solid var(--line)}.flow .positive{border-color:#b7dfca;background:var(--mint)}.flow .negative{border-color:#f0c5aa;background:var(--peach)}.flow strong{display:block;font-size:1.65rem;line-height:1.25}
.meter{height:7px;background:#eeeaf7;margin:12px 0 4px;border-radius:8px;overflow:hidden}.meter i{display:block;height:100%;background:#b7a8f1;border-radius:8px}.health-list{margin-top:8px}.health-list .row{padding:14px 0}.health-list .fix{max-width:35ch;color:var(--sub);font-size:.9rem}
code{font:.9em ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--lavender);padding:2px 5px;border-radius:3px}\n.portfolio{margin-top:44px}.portfolio-row{padding:14px 0;border-top:1px solid var(--line);display:flex;gap:16px;align-items:center;justify-content:space-between}.portfolio-name{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.portfolio-stats{display:flex;gap:14px;flex-wrap:wrap;color:var(--sub);font-size:.88rem}.portfolio-totals{margin:14px 0}.portfolio-list{border-bottom:1px solid var(--line)}
@media(max-width:600px){main{padding:22px 15px 54px}.portfolio-row{display:block}.portfolio-stats{margin-top:8px}.row{display:block}.row .sub,.row .fix{margin-top:6px;max-width:none}.flow{grid-template-columns:1fr}.bars{gap:5px}.summary-meta{width:100%}}
"""


def _card(label: str, big: str, note: str = "") -> str:
    return f'<div class="card"><div class="label">{esc(label)}</div><div class="big">{esc(big)}</div><div class="sub">{esc(note)}</div></div>'


def _bars(days: list[dict]) -> str:
    top = max([d["opened"] for d in days] + [d["closed"] for d in days] + [1])
    cols = "".join(f'<div class="chart-day"><div class="chart-values"><span>{d["opened"]}</span><span>{d["closed"]}</span></div><span class="bar"><i class="o" style="height:{max(2, d["opened"] / top * 100):.0f}%" title="{d["opened"]} added"></i><i class="c" style="height:{max(2, d["closed"] / top * 100):.0f}%" title="{d["closed"]} delivered"></i></span><span class="chart-label">{esc(d["day"])}</span></div>' for d in days)
    return f'<div class="bars" role="img" aria-label="Daily stories added and delivered; values are printed above each pair of bars">{cols}</div><p class="sub">Each day shows stories added and delivered. Values are printed above the bars; the scale is shared across the week.</p>'


def _attention_html(snap: dict) -> str:
    if not snap["waiting"]:
        return '<div class="card">Nothing needs you right now. Work can move without an owner decision.</div>'
    explanations = {
        "Stories to split": ("These stories are too large to finish in one run. Breaking them into smaller pieces gives the runner clearer checkpoints.", "Review the story and split it into smaller, independently deliverable pieces."),
        "Approvals": ("Work is paused until you approve a change. OliverCode will not make this decision for you.", "Read the proposed change and approve or decline it."),
        "Failed checks": ("A required check did not pass, so the story is not ready to land. A failure is evidence to investigate, not automatically a code defect.", "Open the story and inspect the failed check before deciding what to do."),
        "Cleanup": ("Leftover branches or worktrees can make it harder to tell which changes are current and safe to keep.", "Review the named branch or worktree; keep useful work and remove only what is confirmed obsolete."),
        "Setup": ("A local configuration or environment issue may prevent the runner from doing reliable work.", "Follow the specific fix below, then rerun the health check."),
        "Other": ("This item did not fit a known category. Read its details before taking action.", "Review the item and decide whether it needs you or can be returned to the queue."),
    }
    blocks = []
    for g in snap["groups"]:
        why, next_step = explanations.get(g["name"], explanations["Other"])
        items = "".join(f'<li><b>#{esc(i.get("id"))}</b><div>{esc(str(i.get("step", "")).splitlines()[0][:160])}</div></li>' for i in g["steps"][:8])
        more = f'<li class="sub">And {len(g["steps"]) - 8} more in this group.</li>' if len(g["steps"]) > 8 else ""
        blocks.append(
            f'<details class="attention"><summary><span class="summary-title">{esc(g["name"])}</span><span class="summary-meta">{len(g["steps"])} · {esc(g["means"])}</span></summary>'
            f'<div class="expansion"><p><b>Why it matters</b><br>{esc(why)}</p><p><b>What to do</b><br>{esc(next_step)}</p>'
            f'<ul>{items}{more}</ul></div></details>'
        )
    return f'<p class="section-intro">{plural(snap["waiting"], "item")} is holding work. Each group explains why it matters and what action is appropriate.</p>{"".join(blocks)}<p class="note">Full list: <code>olivercode owner list</code></p>'

def _health_html(snap: dict) -> str:
    bad = {s["area"] for s in snap["setup"]}
    marks = "".join(f'<span class="pill {"warn" if a in bad else "good"}">{esc(a)} · {"needs attention" if a in bad else "clear"}</span> ' for a in AREAS)
    rows = "".join(f'<div class="row"><div><b>{esc(s["headline"])}</b><div class="sub">{esc(s["meaning"])}</div></div><div class="fix">{esc(s["fix"])}</div></div>' for s in snap["setup"])
    lead = "A few things could slow the work down. Each includes what it means and the next step." if snap["setup"] else "All six checks are clear. Nothing in the setup is flagged."
    return f'<div class="card"><p><b>{esc(lead)}</b></p><div class="cards">{marks}</div><div class="health-list">{rows}</div></div>'

def dashboard_html(snap: dict) -> str:
    """City: a narrative operating view, readable expansions and grounded comparisons."""
    runner, nums = snap["runner"], snap["numbers"]
    pill = f'<span class="pill {"good" if runner["building"] else ""}">{"Running" if runner["building"] else "Idle"}</span>'
    latest = f'<p class="note">Latest delivery: <b>#{esc(snap["latest"]["number"])} {esc(snap["latest"]["title"])}</b></p>' if snap.get("latest") else ""
    budget = local_config.max_story_spend()
    if nums.get("tokens_per_closed") is not None:
        actual = nums.get("cost_per_closed")
        if actual is None:
            cost_note = f"~{_millions(nums['tokens_per_closed'])} tokens each · ${budget:.2f} budget"
        else:
            cost_note = f"~{_millions(nums['tokens_per_closed'])} tokens each · {'within' if actual <= budget else 'over'} ${budget:.2f} budget"
        cost = (_money(actual), cost_note)
    else:
        cost = ("Not recorded", f"${budget:.2f} per-story budget · no completed stories in this window")
    load = f'<p class="note">{esc(runner["load"])}</p>' if runner.get("load") else ""
    allowed = max(int(runner["allowed"]) or 1, 1)
    meter = f'<div class="meter" aria-label="{runner["building"]} of {allowed} builder slots in use"><i style="width:{min(100, runner["building"] / allowed * 100):.0f}%"></i></div>'
    net = snap["closed"] - snap["opened"]
    net_label = "Net backlog reduction" if net > 0 else ("Net backlog growth" if net < 0 else "No net change")
    ratio = "No new work arrived" if not snap["opened"] else f'{snap["closed"] / snap["opened"]:.1f} deliveries per story added'
    pace = f'{snap["closed"] / 7:.1f} delivered/day · {snap["opened"] / 7:.1f} added/day'
    if net > 0:
        reading = f'Delivery exceeded incoming work by {net} stories this week. The open queue is moving in the right direction.'
    elif net < 0:
        reading = f'Incoming work exceeded delivery by {abs(net)} stories this week. The open queue grew, so capacity or intake needs a closer look.'
    else:
        reading = "Delivery matched incoming work this week. The queue held steady."
    benchmark = f'To shrink the queue, delivery must exceed incoming work ({snap["opened"]} added this week; at least {snap["opened"] + 1} deliveries).' if snap["opened"] else "No new stories arrived this week; any delivery reduces the queue."
    daily = "".join(f'<li>{esc(d["day"])}: {d["closed"]} delivered · {d["opened"]} added</li>' for d in snap["days"])
    next_up = f'<p><b>Next up:</b> {esc(snap["ready"])}</p>' if snap["ready"] else ""
    cards = "".join([
        _card("Stories in the queue", str(snap["open"]), f'{len(snap["today"])} delivered today'),
        _card("Waiting on you", str(snap["waiting"]), "decisions, approvals or fixes"),
        _card("Cost per delivery", cost[0], cost[1]),
        _card("Delivered today", str(len(snap["today"])), f'{snap["today_tokens"]:,} tokens · {_money(snap["today_cost"])}'),
    ])
    flow = (
        f'<div class="flow"><div><span class="label">Delivered</span><strong>{snap["closed"]}</strong><span class="note">this week</span></div>'
        f'<div><span class="label">Added</span><strong>{snap["opened"]}</strong><span class="note">this week</span></div>'
        f'<div class="{"positive" if net >= 0 else "negative"}"><span class="label">{esc(net_label)}</span><strong>{net:+}</strong><span class="note">stories · 7 days</span></div></div>'
    )
    return (
        f'<div class="eyebrow">OliverCode · Live operating picture</div><h1>OliverCode City</h1>'
        f'<p class="lede">{esc(summary_line(snap))} <span class="sub">Updated {esc(snap["now"].strftime("%A, %H:%M"))}.</span></p>'
        f'<div class="cards">{cards}</div>'
        f'<section><h2>What needs your attention</h2><p class="section-intro">Owner decisions come first. They are the work only you can unblock.</p>{_attention_html(snap)}</section>'
        f'<section><h2>Work underway</h2><div class="card"><div>{pill} <b>{runner["building"]} of {allowed} builder slots in use</b></div>{meter}{load}'
        f'<p>{esc("Nothing is building at the moment." if not runner["building"] else "Stories are moving through the runner.")}</p>{next_up}{latest}</div></section>'
        f'<section><h2>Delivery pace</h2><div class="card"><b>{esc(snap["trend"][0])}</b><p class="sub">{esc(snap["trend"][1])}</p>'
        f'{_bars(snap["days"])}<div class="legend"><span>Added</span><span class="delivered">Delivered</span></div>{flow}'
        f'<p class="note"><b>What the trend says:</b> {esc(reading)}</p><p class="note">{esc(pace)}. {esc(ratio)}. {esc(benchmark)}</p>'
        f'<details><summary><span class="summary-title">Daily breakdown</span><span class="summary-meta">7-day view</span></summary><div class="expansion"><ul>{daily}</ul></div></details>'
        f'<p class="note">Benchmark: deliveries need to stay ahead of incoming work to reduce backlog. This compares with your own queue, not an industry target.</p></div></section>'
        f'<section><h2>System health</h2>{_health_html(snap)}</section>'
        f'<section><h2>Keep exploring</h2><p>{plural(snap["ideas"], "idea")} waiting for review. <code>olivercode candidates</code></p>'
        f'<p class="term">Terminal view</p><p><code>cd {esc(CD_TARGET)}</code> then <code>olivercode status</code>.</p></section>'
    )
