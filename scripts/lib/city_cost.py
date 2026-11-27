"""City v2, the Cost section (#1359): what the work cost and why, summed from the round rows of the run log, with the GitHub budget from `gh-points.json` and
`gh-limit.json`. A figure the files do not hold says so in one line, and none is guessed."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone

from lib import agent_loop, cmd_status, gh_budget

SIZES = ("XS", "S", "M", "L", "XL")
SHOWN_ROUTES = 6
SHOWN_STORIES = 5

STYLE = """<style>
#cost .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:16px}
#cost .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:16px;align-items:start}
#cost .num{font:42px/1.05 Newsreader,Georgia,serif}
#cost .row{display:flex;flex-wrap:wrap;gap:4px 16px;align-items:baseline;padding:8px 0;font-size:15px}#cost .row+.row{box-shadow:0 -1px 0 var(--line)}
#cost .row .t{flex:1 1 200px;min-width:0}
#cost .split{display:flex;height:14px;border-radius:999px;overflow:hidden;gap:2px;background:var(--idlebg)}
#cost .split span{background:var(--ink)}#cost .split span+span{background:#C7C6CF}#cost .split span+span+span{background:var(--accent)}
#cost .bm{background:var(--card);border-radius:20px;padding:20px;display:flex;flex-direction:column;gap:8px;min-width:0}
</style>"""


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def money(value: float) -> str:
    return f"${value:,.2f}"


def rounds(log: list[dict]) -> list[dict]:
    """The builder and reader round rows, which carry the cost and the tokens."""
    return [r for r in log if "round" in r and "stage" not in r]


def spend(rows: list[dict]) -> float:
    return sum(float(r.get("cost_usd") or 0) for r in rows)


def landed_stories(log: list[dict]) -> list[dict]:
    """Each landed story as {story, size, cost}: its cost is its rounds between the claim and the landing, reader reviews included."""
    found = []
    for row in cmd_status.landings(log):
        claimed = cmd_status._story_rows(log, row["story"], upto="landed")[0]
        found.append({"story": row["story"], "size": claimed.get("size") or "", "cost": row["cost"]})
    return found


def card(title: str, body: str) -> str:
    return f'<div class="card"><h3>{esc(title)}</h3>{body}</div>'


def tile(label: str, number: str, note: str) -> str:
    return f'<div class="bm"><span class="small">{esc(label)}</span><span class="num">{esc(number)}</span><p class="small">{esc(note)}</p></div>'


def by_model(rows: list[dict]) -> str:
    models: dict[str, list[dict]] = {}
    for r in rows:
        models.setdefault(str(r.get("model") or "model not recorded"), []).append(r)
    total, count = spend(rows), len(rows)
    lines = "".join(f'<div class="row"><span class="t">{esc(m.title())}</span><span>{len(rs)} rounds, {money(spend(rs))}</span>'
                    f'<span class="small">{money(spend(rs) / len(rs))} a round</span></div>' for m, rs in sorted(models.items(), key=lambda kv: -spend(kv[1])))
    return card("Spend and rounds by model", f'<p class="small">{count} rounds cost {money(total)} in all.</p>{lines}')


def by_size(landed: list[dict]) -> str:
    """The median and highest cost per landed story of each size, against the size's limit from COST_CEILING. L and XL have no limit, and it says so."""
    lines = []
    for size in SIZES:
        costs = sorted(s["cost"] for s in landed if s["size"] == size)
        if not costs:
            continue
        limit = agent_loop.COST_CEILING.get(size)
        against = f"limit {money(limit)}, highest uses {round(100 * costs[-1] / limit)}%" if limit else "no limit is set for this size"
        lines.append(f'<div class="row"><b>{size}</b><span class="t">{len(costs)} landed, median {money(cmd_status.median(costs))}, highest {money(costs[-1])}</span>'
                     f'<span class="small">{against}</span></div>')
    body = "".join(lines) or '<p class="small">No landed story has a size recorded.</p>'
    return card("Cost per story by size", body)


def routes(rows: list[dict]) -> str:
    counted = Counter(str(r["route"]) for r in rows if r.get("route")).most_common(SHOWN_ROUTES)
    if not counted:
        return card("Why each model was chosen", '<p class="small">No round has recorded why its model was chosen.</p>')
    top = counted[0][1]
    lines = "".join(f'<div class="row"><span class="t">{esc(why)}</span><b>{n}</b><div class="meter" style="flex:1 1 100%"><span style="width:{round(100 * n / top)}%"></span></div></div>'
                    for why, n in counted)
    return card("Why each model was chosen", lines)


def token_kinds(rows: list[dict]) -> tuple[dict, float | None]:
    kinds = {"Read from cache": sum(int(r.get("cache_read") or 0) for r in rows), "Written to cache": sum(int(r.get("cache_write") or 0) for r in rows),
             "Written": sum(int(r.get("output") or 0) for r in rows), "Fresh input": sum(int(r.get("input") or 0) for r in rows)}
    all_tokens = sum(kinds.values())
    return kinds, (100 * kinds["Read from cache"] / all_tokens if all_tokens else None)


def tokens(rows: list[dict]) -> tuple[str, str]:
    """The tokens-by-kind card and the cache-share text."""
    kinds, share = token_kinds(rows)
    if share is None:
        return card("Tokens", '<p class="small">No tokens are recorded.</p>'), "not recorded"
    bar = "".join(f'<span style="flex:{n}" title="{esc(k)}"></span>' for k, n in kinds.items() if n)
    keys = "".join(f'<div class="row"><span class="t">{esc(k)}</span><b>{n:,}</b></div>' for k, n in kinds.items())
    starts = [int(r["start_tokens"]) for r in rows if r.get("start_tokens")]
    start = (f"A builder loads {sum(starts) // len(starts):,} tokens of context on average before it starts."
             if starts else "Starting context is not recorded.")
    return card("Tokens", f'<div class="split" aria-label="Tokens by kind">{bar}</div>{keys}<p class="small">{esc(start)}</p>'), f"{share:.1f}%"


def priciest(landed: list[dict]) -> str:
    top = sorted(landed, key=lambda s: -s["cost"])[:SHOWN_STORIES]
    lines = "".join(f'<div class="row"><b>#{esc(s["story"].rsplit("-", 1)[-1])}</b><span class="t">{esc(s["size"] or "size not recorded")}</span>'
                    f'<b>{money(s["cost"])}</b></div>' for s in top)
    return card("Most expensive landed stories", lines or '<p class="small">No story has landed.</p>')


def read_json(name: str) -> dict:
    try:
        found = json.loads((gh_budget.home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def clock(stamp) -> str:
    return f"{datetime.fromtimestamp(float(stamp), timezone.utc):%d %b %H:%M} UTC"


def github_budget() -> str:
    """GraphQL points and REST calls left, and when the points reset, from the last reading, and the latest hold from `gh-limit.json`."""
    points, held = read_json("gh-points.json"), read_json("gh-limit.json")
    if "remaining" in points:
        lines = [f"GraphQL points left: {points['remaining']:,}" + (f", resetting at {clock(points['reset'])}" if points.get("reset") else ", reset time not recorded"),
                 f"REST calls left: {points['rest']:,}, reset time not recorded" if "rest" in points else "REST calls left: not recorded"]
        if points.get("at"):
            lines.append(f"Read at {clock(points['at'])}.")
    else:
        lines = ["GraphQL points and REST calls left: not recorded, because no reading has been saved."]
    holds = [f"{name} held until {clock(held[key])}" for name, key in (("GraphQL", "graphql"), ("REST", "rest")) if held.get(key)]
    lines.append(("Latest hold: " + ", ".join(holds) + ".") if holds else "No hold is recorded.")
    lines.append("Only the latest hold is recorded, so earlier holds are not shown.")
    return card("GitHub budget", "".join(f'<p class="small">{esc(line)}</p>' for line in lines))


def render(data: dict) -> str:
    """The Cost section as HTML, from the page's figures in DATA."""
    head = '<section class="chap" id="cost" aria-labelledby="c0"><h2 id="c0">Cost</h2>' + STYLE
    log = data.get("log")
    if log is None:
        return head + '<p class="small">Cost is not recorded, because the run log could not be read.</p>' + github_budget() + "</section>"
    rows = rounds(log)
    if not rows:
        return head + '<p class="small">No round is recorded in the run log yet.</p>' + github_budget() + "</section>"
    landed = landed_stories(log)
    total = spend(rows)
    per_story = (money(sum(s["cost"] for s in landed) / len(landed)), f"{money(sum(s['cost'] for s in landed))} over {len(landed)} landings") if landed else ("not recorded", "No story has landed.")
    token_card, share = tokens(rows)
    read = f"The run log's rounds cost {money(total)}." + (f" Each landed story cost {per_story[0]} on average." if landed else "") + f" Cache share of tokens: {share}."
    tiles = (tile("Cost per landed story", *per_story) + tile("Cache share", share, "Reading from cache is the cheap path.")
             + tile("Cost per round", money(total / len(rows)), f"{len(rows)} rounds, {money(total)}"))
    return (head + f'<p class="small">{esc(read)}</p><div class="tiles">{tiles}</div><div class="grid2">{by_model(rows)}{by_size(landed)}{routes(rows)}{token_card}'
            f'{priciest(landed)}{github_budget()}</div></section>')
