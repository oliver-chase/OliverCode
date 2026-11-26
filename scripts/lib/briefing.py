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
    work = "The runner is paused." if runner.get("paused") else ("Work is running." if runner["building"] else ("There is work ready, but nothing is running." if snap["open"] else "Nothing is waiting to be built."))
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
    if runner.get("paused"):
        out.append("  Runner    Paused — waiting for resume")
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
:root{--bg:#fff;--card:#fff;--ink:#14161a;--sub:#5b6472;--line:#e3e6eb;--good:#1a7f4b;--warn:#b26b00;--bad:#b3261e;--accent:#4f46e5;--soft:#eef0ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1114;--card:#171a1f;--ink:#f1f3f6;--sub:#9aa3b2;--line:#2a2f37;--good:#4cc38a;--warn:#e9a23b;--bad:#f2766e;--accent:#8b86ff;--soft:#1e2140}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.9rem;margin:0}h2{font-size:1.25rem;margin:36px 0 12px}
.sub{color:var(--sub)}.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}.big{font-size:2.2rem;font-weight:650;line-height:1.1}.label{color:var(--sub);font-size:.9rem}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.8rem;font-weight:600;background:var(--soft);color:var(--accent)}
.pill.good{color:var(--good);background:color-mix(in srgb,var(--good) 14%,transparent)}.pill.warn{color:var(--warn);background:color-mix(in srgb,var(--warn) 14%,transparent)}.pill.bad{color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,transparent)}
.bars{display:flex;align-items:flex-end;gap:10px;height:120px;margin-top:8px}.bars div{flex:1;text-align:center;font-size:.75rem;color:var(--sub);display:flex;flex-direction:column;justify-content:flex-end;height:100%}
.bar{display:flex;gap:2px;align-items:flex-end;justify-content:center;flex:1}.bar i{display:block;width:45%;border-radius:4px 4px 0 0;min-height:2px}.o{background:var(--line)}.c{background:var(--accent)}
.meter{height:10px;border-radius:6px;background:var(--line);overflow:hidden;margin-top:8px}.meter i{display:block;height:100%;background:var(--accent)}
details{border-top:1px solid var(--line);padding:8px 0}summary{cursor:pointer;font-weight:600}code{font:.9em ui-monospace,Menlo,monospace;background:var(--soft);padding:1px 6px;border-radius:6px}
ul{margin:6px 0 0;padding-left:20px}.row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;border-top:1px solid var(--line);padding:10px 0}
.term{margin-top:32px;color:var(--sub);font-size:.95rem}
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
        return '<div class="card">Nothing needs you right now.</div>'
    blocks = []
    for g in snap["groups"]:
        items = "".join(f"<li>#{esc(i.get('id'))} {esc(str(i.get('step', '')).splitlines()[0][:160])}</li>" for i in g["steps"][:8])
        more = f"<li>and {len(g['steps']) - 8} more</li>" if len(g["steps"]) > 8 else ""
        blocks.append(f'<details><summary>{esc(g["name"])} · {len(g["steps"])} <span class="sub">{esc(g["means"])}</span></summary><ul>{items}{more}</ul></details>')
    return (f'<div class="card"><p><b>{plural(snap["waiting"], "thing")} {"is" if snap["waiting"] == 1 else "are"} waiting.</b> '
            f'See them all with <code>olivercode owner list</code>.</p>{"".join(blocks)}</div>')


def _health_html(snap: dict) -> str:
    bad = {s["area"] for s in snap["setup"]}
    marks = "".join(f'<span class="pill {"warn" if a in bad else "good"}">{esc(a)}: {"needs attention" if a in bad else "good"}</span> ' for a in AREAS)
    rows = "".join(f'<div class="row"><div><b>{esc(s["headline"])}</b><div class="sub">{esc(s["meaning"])}</div></div><div class="sub">{esc(s["fix"])}</div></div>' for s in snap["setup"])
    lead = (f"{plural(len(snap['setup']), 'thing')} to fix. OliverCode is working, but a few things could get in its way." if snap["setup"]
            else "Everything checks out.")
    return f'<div class="card"><p><b>{esc(lead)}</b></p><p>{marks}</p>{rows}</div>'


def dashboard_html(snap: dict) -> str:
    """City's top half: four questions answered in order, then the terminal commands. Everything is escaped."""
    runner, nums = snap["runner"], snap["numbers"]
    state = "Paused" if runner.get("paused") else ("Running" if runner["building"] else "Idle")
    pill = f'<span class="pill {"warn" if runner.get("paused") else ("good" if runner["building"] else "")}">{state}</span>'
    latest = f'<p>Most recent delivery: <b>#{esc(snap["latest"]["number"])} {esc(snap["latest"]["title"])}</b></p>' if snap.get("latest") else ""
    cost = (f'{_money(nums.get("cost_per_closed"))}', f'about {_millions(nums["tokens_per_closed"])} tokens each') if nums.get("tokens_per_closed") is not None else ("Not recorded", "no finished stories yet")
    load = f'<div class="label">{esc(runner["load"])}</div>' if runner.get("load") else ""
    allowed = max(int(runner["allowed"]) or 1, 1)
    meter = f'<div class="meter"><i style="width:{min(100, runner["building"] / allowed * 100):.0f}%"></i></div>'
    return (
        f'<h1>OliverCode City</h1><p class="sub">{esc(summary_line(snap))} Updated {esc(snap["now"].strftime("%A %H:%M"))}.</p>'
        f'<div class="cards">{_card("Stories open", str(snap["open"]), f"{len(snap["today"])} delivered today")}'
        f'{_card("Waiting on you", str(snap["waiting"]), "approvals, fixes and decisions")}'
        f'{_card("Cost per finished story", cost[0], cost[1])}'
        f'{_card("Delivered today", str(len(snap["today"])), f"{snap["today_tokens"]:,} tokens · {_money(snap["today_cost"])}")}</div>'
        f'<h2>What needs your attention</h2>{_attention_html(snap)}'
        f'<h2>What OliverCode is doing</h2><div class="card">{pill} <b>{esc(plural(runner["building"], "builder"))} running</b> of {allowed} allowed{meter}{load}'
        f'<p>{esc("Paused: no new stories will start. " if runner.get("paused") else ("Nothing is building right now. " if not runner["building"] else ""))}{esc("Next up: " + snap["ready"] if snap["ready"] else "")}</p>{latest}</div>'
        f'<h2>How work is going</h2><div class="card"><b>{esc(snap["trend"][0])}</b><p class="sub">{esc(snap["trend"][1])}</p>{_bars(snap["days"])}'
        f'<div class="cards"><div><div class="label">Delivered</div><div class="big">{snap["closed"]}</div></div><div><div class="label">Added</div><div class="big">{snap["opened"]}</div></div></div>'
        f'<p class="sub">Work moved to a fresh session {plural(nums.get("handovers", 0), "time")}, and you stepped into {plural(nums.get("threads", 0), "thread")}. '
        f'{plural(snap["ideas"], "idea")} waiting for review (<code>olivercode candidates</code>).</p></div>'
        f'<h2>How the system is doing</h2>{_health_html(snap)}'
        f'<p class="term">To see this in a terminal: <code>cd {esc(CD_TARGET)}</code> then <code>olivercode status</code>.</p>'
    )
