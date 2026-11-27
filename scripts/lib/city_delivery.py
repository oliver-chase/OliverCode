"""City v2, the Delivery section and Activity chart (#1358), drawn only from run-log.jsonl and city-github.json.

Landings are counted from the landed stage rows and never from the run-end rows. A figure the log does not record says so in one line."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone

from lib import agent_loop, cmd_status

HOUR, DAY = 3600, 86400
VIEWS = {"twoh": ("2 hours", 12, 2 * HOUR), "day": ("Day", 24, HOUR), "week": ("Week", 7, DAY), "month": ("Month", 30, DAY)}
METRICS = {"landed": "Landed", "spend": "Spend ($)", "rounds": "Rounds", "tokens": "Tokens (thousands)"}
SCRIPT = """
(function(){var d=JSON.parse(document.getElementById("activity-data").textContent),v="twoh",m="landed",box=document.getElementById("activity-chart");
function draw(){var xs=d[v][m],top=Math.max.apply(null,xs.concat([0.0001])),n=xs.length,w=100/n,s="";
xs.forEach(function(x,i){var h=Math.round(x/top*100);s+='<g><title>'+d[v].labels[i]+': '+x+'</title><rect x="'+(i*w+w*0.1)+'" y="'+(100-h)+'" width="'+(w*0.8)+'" height="'+h+'" fill="currentColor"/></g>'});
box.innerHTML=s;document.getElementById("activity-total").textContent="Total "+(Math.round(xs.reduce(function(a,b){return a+b},0)*100)/100)+" over the "+d[v].span+".";
document.querySelectorAll("[data-view],[data-metric]").forEach(function(b){b.setAttribute("aria-pressed",String(b.dataset.view===v||b.dataset.metric===m))})}
document.addEventListener("click",function(e){var b=e.target.closest("[data-view],[data-metric]");if(!b)return;if(b.dataset.view)v=b.dataset.view;else m=b.dataset.metric;draw()});draw()})();
"""


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def _day(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")


def activity(log: list[dict], now: float) -> tuple[dict, int]:
    """({view: {landed, spend, rounds, tokens, labels, span}}, untimed rounds). Each bucket counts back from NOW. A round with no timestamp is left out of
    every bucket and counted in the second figure."""
    out = {}
    for key, (name, n, width) in VIEWS.items():
        out[key] = {m: [0] * n if m in ("landed", "rounds") else [0.0] * n for m in METRICS}
        out[key]["labels"] = [datetime.fromtimestamp(now - (n - 1 - i) * width, timezone.utc).strftime("%H:%M" if width < DAY else "%m-%d") for i in range(n)]
        out[key]["span"] = {"twoh": "last 24 hours in 2-hour steps", "day": "last 24 hours", "week": "last 7 days", "month": "last 30 days"}[key]
    untimed = 0
    for row in log:
        is_round = "round" in row and "stage" not in row
        if not is_round and row.get("stage") != "landed":
            continue
        at = cmd_status._epoch(row.get("at"))
        if is_round and not at:
            untimed += 1
            continue
        for key, (_, n, width) in VIEWS.items():
            back = int((now - at) // width)
            if not 0 <= back < n:
                continue
            i, bucket = n - 1 - back, out[key]
            if is_round:
                bucket["rounds"][i] += 1
                bucket["spend"][i] = round(bucket["spend"][i] + float(row.get("cost_usd") or 0), 4)
                bucket["tokens"][i] = round(bucket["tokens"][i] + (int(row.get("input") or 0) + int(row.get("output") or 0)) / 1000, 2)
            else:
                bucket["landed"][i] += 1
    return out, untimed


def activity_card(log: list[dict], now: float) -> str:
    chart, untimed = activity(log, now)
    payload = json.dumps(chart).replace("<", "\\u003c")
    views = "".join(f'<button class="btn" data-view="{k}" aria-pressed="false">{v[0]}</button>' for k, v in VIEWS.items())
    metrics = "".join(f'<button class="btn" data-metric="{k}" aria-pressed="false">{v}</button>' for k, v in METRICS.items())
    left = (f'<p class="small">{untimed} rounds have no timestamp, so the chart leaves them out.</p>' if untimed else "")
    return ('<div class="card" id="activity"><h3>Activity</h3>'
            f'<div class="acts" role="group" aria-label="Range">{views}</div><div class="acts" role="group" aria-label="Measure">{metrics}</div>'
            '<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:160px;color:var(--accent)" role="img" aria-label="Activity chart">'
            '<g id="activity-chart"></g></svg>'
            f'<p class="small" id="activity-total"></p>{left}<script type="application/json" id="activity-data">{payload}</script><script type="text/javascript">{SCRIPT}</script></div>')


def review_figures(log: list[dict]) -> tuple[int, int, str]:
    """(stories reviewed, passed on the first review, the latest defect's text). The latest defect is the findings of the newest review that did not pass."""
    first: dict[str, str] = {}
    defect = ""
    for row in log:
        if "review" not in row:
            continue
        first.setdefault(str(row.get("story")), row["review"])
        if row["review"] != "pass" and row.get("findings"):
            defect = row["findings"]
    return len(first), sum(1 for v in first.values() if v == "pass"), cmd_status._text(defect, 300)


def histogram(log: list[dict], found: list[dict]) -> list[tuple[str, int]]:
    """How many landed stories took 1, 2, 3, 4 and 5 or more builder and reader rounds."""
    counts: Counter = Counter()
    for f in found:
        rounds = sum(1 for r in cmd_status._story_rows(log, f["story"], upto="landed") if "round" in r and "stage" not in r)
        counts[min(max(rounds, 1), 5)] += 1
    return [("5 or more" if k == 5 else str(k), counts[k]) for k in range(1, 6)]


def landed_line(row: dict) -> str:
    cost = f"${row['cost']:.2f}" if row["cost"] else "cost not recorded"
    return f"#{row['story'].rsplit('-', 1)[-1]} in {row['repo']} landed {datetime.fromtimestamp(row['at'], timezone.utc):%Y-%m-%d %H:%M} UTC, {cmd_status.minutes(row['total'])}, {cost}"


def flow(github: dict | None) -> str:
    if github and github.get("opened") is not None and github.get("closed") is not None:
        return (f"{github['closed']} closed as completed against {github['opened']} opened in the last {cmd_status.DAYS} days. "
                f"Read from GitHub at {datetime.fromtimestamp(github['read_at'], timezone.utc):%H:%M} UTC.")
    return "Backlog flow: not recorded yet. Run <code>olivercode status page --fetch</code> to read it from GitHub once."


def render(data: dict) -> str:
    """The Delivery section as HTML, from the page's figures in DATA."""
    log, now = data.get("log"), data["now"].timestamp()
    head = '<section class="chap" id="delivery" aria-labelledby="d0"><h2 id="d0">Delivery</h2>'
    if log is None:
        return head + '<p class="small">Delivery: unknown, because the run log could not be read.</p></section>'
    found = cmd_status.landings(log)
    days = Counter(_day(f["at"]) for f in found)
    best = max(days.items(), key=lambda kv: kv[1], default=None)
    week = sum(1 for f in found if f["at"] >= now - cmd_status.DAYS * DAY)
    reviewed, passed, defect = review_figures(log)
    stopped = [r for r in log if r.get("stage") == "stopped"]
    reasons = Counter(cmd_status._text(r.get("reason") or "no reason recorded", 120) for r in stopped)
    stats = [("Best day", f"{best[1]} landed on {best[0]}" if best else "Nothing has landed yet."), ("Landed in 7 days", str(week)),
             ("Landed today", str(days[_day(now)])),
             ("Review first pass", f"{round(100 * passed / reviewed)}% of {reviewed} reviewed stories" if reviewed else "Not recorded: no review rows."),
             ("Stopped", str(len(stopped)))]
    cards = "".join(f'<div class="card"><h3>{esc(k)}</h3><p class="count">{esc(v)}</p></div>' if v.isdigit() else f'<div class="card"><h3>{esc(k)}</h3><p>{esc(v)}</p></div>'
                    for k, v in stats)
    why = "".join(f"<p>{n} × {esc(r)}</p>" for r, n in reasons.most_common()) or '<p class="small">No story has stopped.</p>'
    rounds = histogram(log, found)
    top = max((n for _, n in rounds), default=0) or 1
    bars = "".join(f'<p>{k} <span style="display:inline-block;height:10px;width:{round(n / top * 60)}%;background:var(--accent);border-radius:5px"></span> {n}</p>' for k, n in rounds)
    stages = [f"{name} {cmd_status.minutes(cmd_status.median([f[key] for f in found]))}" for name, key in (("building", "build"), ("validating", "check"), ("landing", "land"))] if found else []
    time = " · ".join(stages) or "Not recorded: nothing has landed."
    ceiling = f"The M ceiling is ${agent_loop.COST_CEILING['M']:.2f} a story."
    recent = "".join(f"<p>{esc(landed_line(f))}</p>" for f in found[:5]) or '<p class="small">Nothing has landed yet.</p>'
    spend = sum(float(r.get("cost_usd") or 0) for r in log if "round" in r and "stage" not in r)
    last = f"<p>{esc(defect)}</p>" if defect else '<p class="small">No review defect is recorded.</p>'
    return (head + activity_card(log, now) + f'<div class="body" style="padding:0;gap:16px">{cards}</div>'
            f'<div class="card"><h3>Why stories stopped</h3>{why}</div><div class="card"><h3>Rounds per story</h3>{bars}</div>'
            f'<div class="card"><h3>Median time per stage</h3><p>{esc(time)}</p></div>'
            f'<div class="card"><h3>Recent landings</h3>{recent}<p class="small">{esc(ceiling)} The run log sums to ${spend:.2f} in all.</p></div>'
            f'<div class="card"><h3>Latest review defect</h3>{last}</div><div class="card"><h3>Backlog flow</h3><p>{flow(data.get("github"))}</p></div></section>')
