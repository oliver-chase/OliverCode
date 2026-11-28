"""City v2, the Delivery section and Activity chart (#1358, #1383), in the mockup's markup and drawn only from run-log.jsonl and city-github.json.

Landings are counted from the landed stage rows and never from the run-end rows. A figure the log does not record says so in one line."""

from __future__ import annotations

import html
import json
import re
from collections import Counter

from lib import local_config, cmd_status
from lib.city_health import esc

HOUR, DAY = 3600, 86400
VIEWS = {"twoh": ("2 hours", 12, 600), "day": ("Day", 24, HOUR), "week": ("Week", 7, DAY), "month": ("Month", 30, DAY)}
METRICS = {"landed": "Landed", "spend": "Spend", "rounds": "Rounds", "tokens": "Tokens"}
SCRIPT = """
(function(){var d=JSON.parse(document.getElementById("activity-data").textContent),v="day",m="landed";
function fmt(x){return m==="spend"?"$"+x.toFixed(2):m==="tokens"?x.toFixed(1)+"k":String(Math.round(x*10)/10)}
function draw(){var s=d[v],xs=s[m],n=xs.length,max=Math.max.apply(null,xs.concat([0])),tot=xs.reduce(function(a,b){return a+b},0),act=xs.filter(function(x){return x>0}).length,avg=act?tot/act:0,mi=xs.indexOf(max),every=v==="week"?1:v==="month"?5:3,bars="",labs="";
xs.forEach(function(x,i){var none=s.none.indexOf(i)>=0,top=i===mi&&x>0;
bars+='<div class="col"><div class="barv" style="height:'+(none?"100%":x>0?(x/max*100).toFixed(1)+"%":"2px")+';background:'+(none?"#EFEFF1":top?"#4C3FB0":x>0?"#17161C":"#C7C6CF")+'">'+(top?'<span class="peak">'+fmt(x)+'</span>':"")+'</div></div>';
labs+="<span>"+(i%every===0||i===n-1?s.labels[i]:"")+"</span>"});
var what={landed:Math.round(tot)+" stories landed",spend:"$"+tot.toFixed(2)+" was spent",rounds:Math.round(tot)+" builder rounds ran",tokens:tot.toFixed(1)+" thousand tokens were used"}[m],
when={twoh:"in the last 2 hours",day:"in the last 24 hours",week:"in the last 7 days",month:"in the last 30 days"}[v],
peak=v==="twoh"?"The busiest 10 minutes began at ":v==="day"?"The busiest hour began at ":"The busiest day was ",
per={twoh:"each active 10 minutes",day:"each active hour",week:"each active day",month:"each active day"}[v],
cap=tot>0?what+" "+when+". "+peak+s.labels[mi]+", at "+fmt(max)+", against an average of "+fmt(avg)+" for "+per+".":"Nothing was recorded "+when+".",
shaded=(v==="week"||v==="month")&&s.none.length&&s.since;
var box=document.getElementById("activity-chart");box.setAttribute("aria-label",cap);
box.innerHTML=bars+'<div class="avg" style="bottom:'+(max>0?(avg/max*100).toFixed(1):0)+'%"><span>Average '+fmt(avg)+'</span></div>';
document.getElementById("activity-labels").innerHTML=labs;document.getElementById("activity-caption").textContent=cap;
document.getElementById("activity-foot").textContent=(shaded?"Records start on "+s.since+", so the shaded days have no data. ":"Times are in "+s.zone+". ")+"The dashed line is the average for periods with activity, and the purple bar is the peak.";
document.querySelectorAll("[data-view],[data-metric]").forEach(function(b){var on=b.dataset.view===v||b.dataset.metric===m;b.setAttribute("aria-pressed",String(on));b.className=on?"on":""})}
document.addEventListener("click",function(e){var b=e.target.closest("[data-view],[data-metric]");if(!b)return;if(b.dataset.view)v=b.dataset.view;else m=b.dataset.metric;draw()});document.addEventListener("DOMContentLoaded",draw)})();
"""


def _day(stamp: float) -> str:
    return local_config.local_time(stamp, "%Y-%m-%d")


def stamp(at: float, now: float) -> str:
    """AT in the owner's time zone, with its date when it is not today."""
    return local_config.local_time(at) if _day(at) == _day(now) else local_config.local_time(at, "%-d %b %H:%M %Z")


def activity(log: list[dict], now: float) -> tuple[dict, int]:
    """({view: {landed, spend, rounds, tokens, labels, none, since}}, untimed rounds). Each bucket counts back from NOW and is labelled with where it starts. `none`
    lists the buckets that end before the log's first timed row, and `since` says when that row was written. A round with no timestamp is left out of every bucket
    and counted in the second figure."""
    first = min((t for t in (cmd_status._epoch(r.get("at")) for r in log) if t), default=0)
    out = {}
    for key, (name, n, width) in VIEWS.items():
        out[key] = {m: [0] * n if m in ("landed", "rounds") else [0.0] * n for m in METRICS}
        starts = [now - (n - i) * width for i in range(n)]
        out[key]["labels"] = [local_config.local_time(t, "%H:%M") if width < DAY else local_config.local_time(t, "%-d %b") for t in starts]
        out[key]["zone"] = local_config.local_time(now, "%Z")
        out[key]["none"] = [i for i, t in enumerate(starts) if first and t + width <= first]
        out[key]["since"] = local_config.local_time(first, "%-d %b at %H:%M %Z") if first else ""
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
    """The Activity chart in the mockup's markup: the Measure and View by controls, a caption, the columns with an average line, the labels and a footnote, which SCRIPT fills in."""
    chart, untimed = activity(log, now)
    payload = json.dumps(chart).replace("<", "\\u003c")
    metrics = "".join(f'<button aria-pressed="false" data-metric="{k}">{v}</button>' for k, v in METRICS.items())
    views = "".join(f'<button aria-pressed="false" data-view="{k}">{v[0]}</button>' for k, v in VIEWS.items())
    left = f'<p class="small">{untimed} rounds have no timestamp, so the chart leaves them out.</p>' if untimed else ""
    return ('<section class="card" id="activity" aria-labelledby="act" style="padding:28px;gap:18px"><div class="controls"><h3 id="act" style="font-size:30px">Activity</h3>'
            '<div style="display:flex;flex-wrap:wrap;gap:8px">'
            f'<div class="seg" role="group" aria-label="Measure">{metrics}</div><div class="seg" role="group" aria-label="View by">{views}</div></div></div>'
            '<p id="activity-caption" style="font-size:17px;max-width:820px"></p>'
            '<div><div class="chart" id="activity-chart" role="img" aria-label="Activity"></div>'
            f'<script type="application/json" id="activity-data">{payload}</script><script type="text/javascript">{SCRIPT}</script>'  # before the labels, which the script fills
            f'<div class="xl" id="activity-labels" aria-hidden="true"></div></div><p class="small" id="activity-foot"></p>{left}</section>')


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
    """How many landed stories took 1, 2, 3 and 4 or more builder and reader rounds."""
    counts: Counter = Counter()
    for f in found:
        rounds = sum(1 for r in cmd_status._story_rows(log, f["story"], upto="landed") if "round" in r and "stage" not in r)
        counts[min(max(rounds, 1), 4)] += 1
    return [("1 round" if k == 1 else "4 or more" if k == 4 else str(k), counts[k]) for k in range(1, 5)]


def plain(text, limit: int = 120) -> str:
    """The first clause of TEXT on one line, with file paths, commit hashes and the text after a traceback left out."""
    first = re.split(r"(?<=[.!?:])\s|Traceback|\n", str(text or "").strip())[0]
    return cmd_status._text(re.sub(r"\S*/\S*|\b[0-9a-f]{7,40}\b|\S+\.(?:py|sh|md|json|js|html|yml)\b", "...", first), limit)


def fold(rows: list[str], label: str, shown: int, wrap=None, total: int | None = None) -> str:
    """ROWS after the first SHOWN sit behind a See all control, which the page script opens and remembers across the 60-second reload. WRAP joins a run of rows."""
    wrap = wrap or "".join
    if len(rows) <= shown:
        return wrap(rows)
    total = len(rows) if total is None else total
    return f'{wrap(rows[:shown])}<div class="fold" hidden>{wrap(rows[shown:])}</div><a class="more" href="#" data-fold="See all {total} {label}">See all {total} {label}</a>'


def table(head: list[tuple[str, bool]], rows: list[list[str]], label: str, shown: int, total: int | None = None) -> str:
    """A mockup table of HEAD (name, right-aligned) with ROWS of cell markup, the rows past SHOWN folded behind See all."""
    cols = "".join(f'<col style="width:{100 / len(head):.1f}%">' for _ in head)
    top = "<thead><tr>" + "".join(f'<th class="r">{h}</th>' if r else f"<th>{h}</th>" for h, r in head) + "</tr></thead>"
    lines = ["<tr>" + "".join(f'<td class="r">{c}</td>' if head[i][1] else f"<td>{c}</td>" for i, c in enumerate(row)) + "</tr>" for row in rows]
    def wrap(part):
        return f'<div class="tablebox"><table style="table-layout:fixed"><colgroup>{cols}</colgroup>{top if part[0] is lines[0] else ""}<tbody>{"".join(part)}</tbody></table></div>'
    return fold(lines, label, shown, wrap, total)


def flow(github: dict | None) -> str:
    if github and github.get("opened") is not None and github.get("closed") is not None:
        return (f"{github['closed']} closed as completed against {github['opened']} opened in the last {cmd_status.DAYS} days. "
                f"Read from GitHub at {local_config.local_time(github['read_at'])}.")
    return "Backlog flow: not recorded yet. Run <code>olivercode status page --fetch</code> to read it from GitHub once."


def tile(label: str, number: str, fill: float, bench: str, mean: str, mark: bool = False) -> str:
    """One benchmark tile: a figure, a bar filled to FILL percent (with the limit marked at its end when MARK), what it is measured against and what it means."""
    limit = '<i style="left:calc(100% - 2px)"></i>' if mark else ""
    return (f'<div class="bm"><span class="lab">{esc(label)}</span><span class="num">{esc(number)}</span><div class="bullet"><span style="width:{min(max(fill, 0), 100):.1f}%"></span>{limit}</div>'
            f'<span class="bench">{esc(bench)}</span><p class="mean">{mean}</p></div>')


def rounds_chart(rounds: list[tuple[str, int]]) -> str:
    """The rounds-per-story columns as the mockup's SVG, the last column in the accent colour."""
    top = max(n for _, n in rounds) or 1
    bars = labels = ""
    for i, (name, n) in enumerate(rounds):
        x, h = 59 + 110 * i, n / top * 125
        fill, ink = ("#4C3FB0", "#4C3FB0") if i == len(rounds) - 1 else ("#C7C6CF", "#17161C")
        bars += f'<rect x="{x}" y="{160 - h:.1f}" width="72" height="{h:.1f}" rx="5" fill="{fill}"></rect>'
        bars += f'<text x="{x + 36}" y="{152 - h:.1f}" text-anchor="middle" style="font:500 13px Inter,sans-serif;fill:{ink}">{n}</text>'
        labels += f'<text x="{x + 36}" y="182" text-anchor="middle" style="font:12px Inter,sans-serif;fill:#5D5C66">{esc(name)}</text>'
    aria = "Stories by rounds: " + ", ".join(f"{name} {n}" for name, n in rounds)
    return f'<svg viewBox="0 0 480 200" style="width:100%;height:auto" role="img" aria-label="{esc(aria)}"><line x1="40" y1="160" x2="460" y2="160" stroke="#DDDCE3"></line>{bars}{labels}</svg>'


def span(seconds: float) -> str:
    return f"{round(seconds)} s" if seconds < 120 else cmd_status.minutes(seconds)


def landing_rows(log: list[dict], found: list[dict], now: float) -> list[list[str]]:
    """The Recent landings rows: story, size, model, time to land, cost and when it landed."""
    rows = []
    for f in found:
        mine = cmd_status._story_rows(log, f["story"], upto="landed")
        models = Counter(str(r["model"]).title() for r in mine if "round" in r and "stage" not in r and r.get("model"))
        rows.append([f'<span class="n">#{esc(f["story"].rsplit("-", 1)[-1])}</span>', esc(mine[0].get("size") or "Not recorded"), esc(models.most_common(1)[0][0] if models else "Not recorded"),
                     esc(cmd_status.minutes(f["total"])), f"${f['cost']:.2f}" if f["cost"] else "Not recorded", stamp(f["at"], now)])
    return rows


def run_rows(ends: list[dict], now: float) -> list[list[str]]:
    """The Run summaries rows, two runs to a row, each as the time it ended, the stories it landed and the stories it stopped."""
    cells = [[stamp(cmd_status._epoch(r.get("at")), now), str(r.get("landed", 0)), str(r.get("stopped", 0))] for r in ends]
    cells += [["", "", ""]] * (len(cells) % 2)
    return [cells[i] + cells[i + 1] for i in range(0, len(cells), 2)]


def render(data: dict) -> str:
    """The Delivery section as HTML in the mockup's markup, from the page's figures in DATA, behind the Activity chart."""
    log, now = data.get("log"), data["now"].timestamp()
    head = '<section class="chap" id="delivery" aria-labelledby="d0"><h2 id="d0">Delivery</h2>'
    if log is None:
        return head + '<p class="small">Delivery: unknown, because the run log could not be read.</p></section>'
    found = cmd_status.landings(log)
    days = Counter(_day(f["at"]) for f in found)
    best = max(days.items(), key=lambda kv: kv[1], default=None)
    week = sum(1 for f in found if f["at"] >= now - cmd_status.DAYS * DAY)
    today = days[_day(now)]
    reviewed, passed, defect = review_figures(log)
    stopped = [r for r in log if r.get("stage") == "stopped"]
    ends = sorted((r for r in log if r.get("stage") == "run-end"), key=lambda r: cmd_status._epoch(r.get("at")), reverse=True)
    github = data.get("github") or {}
    first = (f"{best[1]} stories landed on {best[0]}, the most in a day so far, and {week} in the last {cmd_status.DAYS} days." if best else "Nothing has landed yet.")
    second = (f"{round(100 * passed / reviewed)}% of {reviewed} reviewed stories passed review first time, and {len(stopped)} stopped." if reviewed
              else f"Review first pass is not recorded, because the log has no review rows, and {len(stopped)} stopped.")
    opened, closed = github.get("opened"), github.get("closed")
    if opened is not None and closed is not None:
        grew = opened - closed
        flat = f"{closed} closed against {opened} opened, so the backlog " + (f"grew by {grew}." if grew > 0 else f"shrank by {-grew}." if grew < 0 else "stayed flat.")
        backlog = tile("Backlog flow", f"{round(100 * closed / opened)}%" if opened else "Not recorded", 100 * closed / opened if opened else 0, "100% keeps the backlog flat", f"{esc(flat)} {flow(github)}", True)
    else:
        backlog = tile("Backlog flow", "Not recorded", 0, "100% keeps the backlog flat", flow(github))
    finished = len(found) + len(stopped)
    tiles = "".join([
        tile("Best day so far", str(best[1]) if best else "Nothing yet", 100 if best else 0, f"Set on {best[0]}" if best else "Nothing has landed yet.",
             f"{week} landed in the last {cmd_status.DAYS} days, and {today} so far today."),
        backlog,
        tile("Passed review first time", f"{round(100 * passed / reviewed)}%" if reviewed else "Not recorded", 100 * passed / reviewed if reviewed else 0,
             f"{passed} of {reviewed} reviews" if reviewed else "No review rows are recorded.", f"The other {reviewed - passed} went back to the builder with defects." if reviewed else "Nothing has been reviewed yet."),
        tile("Stopped", str(len(stopped)), 100 * len(stopped) / finished if finished else 0, f"{round(100 * len(stopped) / finished)}% of finished stories" if finished else "Nothing has finished yet.",
             f"{len(stopped)} stopped against {len(found)} landed.")])
    rounds = histogram(log, found)
    once, many = rounds[0][1], rounds[-1][1]
    cut = (f"<p class=\"mean\">{once} {'story needed' if once == 1 else 'stories needed'} one round. {many} needed four or more, which usually means the story was unclear or hard.</p>{rounds_chart(rounds)}"
           if found else '<p class="mean">Not recorded: nothing has landed.</p>')
    build, check, land = (cmd_status.median([f[k] for f in found]) for k in ("build", "check", "land")) if found else (0, 0, 0)
    colours = ("#C7C6CF", "#8F8E99", "#17161C")
    steps = (("Building", build), ("Validating", check), ("Landing", land))
    stages = (f'<p class="mean">Once built, a story takes about {cmd_status.minutes(check + land)} to validate and land. {"Landing" if land > check else "Validating"} is the slower step.</p>'
              f'<div class="stack" aria-hidden="true">{"".join(f"<span style=\"flex:{max(s, 0)};background:{c}\"></span>" for (_, s), c in zip(steps, colours))}</div>'
              f'<div class="keys">{"".join(f"<span><span class=\"sw\" style=\"background:{c}\"></span>{n} {span(s)}</span>" for (n, s), c in zip(steps, colours))}</div>'
              '<p class="small">Medians across the landed stories.</p>') if found else '<p class="mean">Not recorded: nothing has landed.</p>'
    last = f'<p class="mean">{esc(plain(defect, 200))}</p>' if defect else '<p class="small">No review defect is recorded.</p>'
    kinds = Counter(plain(r.get("reason") or "no reason recorded") for r in stopped).most_common()
    why = fold([f'<div class="row"><span class="t">{esc(k)}</span><b>{n}</b></div>' for k, n in kinds], "kinds", 5) or '<p class="small">No story has stopped.</p>'
    recent = (table([("Story", False), ("Size", False), ("Model", False), ("Time to land", True), ("Cost", True), ("Landed", True)], landing_rows(log, found, now), "landings", 8)
              if found else '<p class="small">Nothing has landed yet.</p>')
    summed = sum(int(r.get("landed") or 0) for r in ends)
    note = f'<p class="note">The run summaries show {summed} landed, but {len(found)} stories landed.</p>' if ends and summed != len(found) else ""
    runs = (note + table([("Run ended", False), ("Landed", True), ("Stopped", True)] * 2, run_rows(ends, now), "runs", 5, len(ends)) + f'<p class="small">{len(ends)} runs ended. Run start times and lengths are not recorded yet.</p>'
            if ends else '<p class="small">No run has ended yet.</p>')
    return (activity_card(log, now) + head + f'<p class="read">{esc(first)} {esc(second)}</p><div class="tiles">{tiles}</div><div class="grid2">'
            f'<div class="card"><h3>Rounds per story</h3>{cut}</div>'
            f'<div class="card"><h3>Time per stage</h3>{stages}<h3 style="padding-top:12px">Latest defect a review found</h3>{last}</div>'
            f'<div class="card"><h3>Why stories stopped</h3><div>{why}</div></div>'
            f'<div class="card"><h3>Recent landings</h3>{recent}</div>'
            f'<div class="card" style="grid-column:1/-1"><h3>Run summaries</h3>{runs}</div></div></section>')
