"""City v2, the Cost section (#1359, #1384): what the work cost and why, summed from the round rows of the run log, with the GitHub budget from `gh-points.json` and
`gh-limit.json`. The markup and classes are the mockup's (docs/city/Main.dc.html), and every figure is a recorded one. A figure the files do not hold says so in one line, and none is guessed."""

from __future__ import annotations

import html
import json
from collections import Counter

from lib import agent_loop, local_config, cmd_status, gh_budget
from lib.city_health import clock, esc, money

SIZES = ("XS", "S", "M", "L", "XL")
SHOWN_ROUTES = 6
SHOWN_STORIES = 5
MODEL_STYLE = {"opus": ("var(--accent)", "#fff"), "sonnet": ("var(--ink)", "#fff"), "haiku": ("var(--data)", "var(--ink)")}  # background and text colour per model, as the mockup
TOKEN_COLOR = {"Read from cache": "var(--ink)", "Written to cache": "var(--data)", "Written": "var(--accent)"}  # as the mockup


def pct(part: float, whole: float) -> float:
    """PART as a percentage of WHOLE, or 0 when WHOLE is 0."""
    return 100 * part / whole if whole else 0.0


def rounds(log: list[dict]) -> list[dict]:
    """The builder and reader round rows, which carry the cost and the tokens."""
    return [r for r in log if "round" in r and "stage" not in r]


def spend(rows: list[dict]) -> float:
    return sum(float(r.get("cost_usd") or 0) for r in rows)


def landed_stories(log: list[dict]) -> list[dict]:
    """Each landed story that records a cost, as {story, size, cost}: its cost is its rounds between the claim and the landing, reader reviews included."""
    found = []
    for row in cmd_status.landings(log):
        rows = cmd_status._story_rows(log, row["story"], upto="landed")
        if cmd_status.priced(rows):
            found.append({"story": row["story"], "size": rows[0].get("size") or "", "cost": row["cost"]})
    return found


def card(title: str, body: str) -> str:
    return f'<div class="card"><h3>{esc(title)}</h3>{body}</div>'


def tile(label: str, number: str, bar: float, bench: str, note: str, mark: bool = False) -> str:
    """A benchmark tile: its figure, a bar filled to BAR percent, a mark at the right end when MARK (the benchmark the bar is read against), and its note."""
    tick = '<i style="left:calc(100% - 2px)"></i>' if mark else ""
    return (f'<div class="bm"><span class="lab">{esc(label)}</span><span class="num">{esc(number)}</span>'
            f'<div class="bullet"><span style="width:{min(bar, 100):.1f}%"></span>{tick}</div><span class="bench">{esc(bench)}</span><p class="mean">{esc(note)}</p></div>')


def by_model_rows(rows: list[dict]) -> dict[str, list[dict]]:
    models: dict[str, list[dict]] = {}
    for r in rows:
        models.setdefault(str(r.get("model") or "model not recorded"), []).append(r)
    return models


def model_style(model: str) -> tuple[str, str]:
    return MODEL_STYLE.get(model.lower(), ("var(--data2)", "var(--ink)"))


def swatch(color: str) -> str:
    return f'<span class="sw" style="background:{color}"></span>' if color else ""


def split(parts: list[tuple[float, str, str, str]], label: str) -> str:
    """A bar of parts, each (amount, text, background, text colour), in proportion to its amount, with its text inside."""
    bar = "".join(f'<span style="flex:{n};background:{bg};color:{fg}" title="{esc(text)}">{esc(text)}</span>' for n, text, bg, fg in parts if n)
    return f'<div class="split" aria-label="{esc(label)}">{bar}</div>'


def tiles(rows: list[dict], landed: list[dict], kinds: dict, share: float | None) -> str:
    """The four benchmark tiles: cost per landed story against the M limit, cache share, the highest story of a size against its limit, and cost per round against the priciest model."""
    costs, limit = [s["cost"] for s in landed], agent_loop.COST_CEILING["M"]
    if costs:
        average = sum(costs) / len(costs)
        story = tile("Cost per landed story", money(average), pct(average, limit), f"{money(sum(costs))} over {len(costs)} landings",
                     f"Against the {money(limit)} M limit. The median landed story cost {money(cmd_status.median(costs))}.", mark=True)
    else:
        story = tile("Cost per landed story", "not recorded", 0, "No landed story has a cost recorded.", "")
    cache = tile("Cache share", f"{share:.1f}%" if share is not None else "not recorded", share or 0, "Higher is cheaper",
                 f"{kinds['Read from cache']:,} tokens were read from cache.")
    worst = []
    for size in SIZES:
        sized = [s["cost"] for s in landed if s["size"] == size]
        if agent_loop.COST_CEILING.get(size) and sized:
            worst.append((max(sized) / agent_loop.COST_CEILING[size], size, max(sized), agent_loop.COST_CEILING[size]))
    if worst:
        ratio, size, highest, size_limit = max(worst)
        ceiling = tile(f"Highest {size} story against its limit", f"{round(100 * ratio)}%", 100 * ratio, f"Limit {money(size_limit)}",
                       f"The highest {size} story cost {money(highest)}.", mark=True)
    else:
        ceiling = tile("Highest story against its limit", "not recorded", 0, "No landed story has a limit to measure against.", "")
    per_round = {m: spend(rs) / len(rs) for m, rs in by_model_rows(rows).items()}
    each = spend(rows) / len(rows) if rows else 0
    if not rows:
        rounded = tile("Cost per round", "not recorded", 0, "No round has a cost recorded.", "")
    elif len(per_round) > 1:
        priciest, cheapest = max(per_round, key=per_round.get), min(per_round, key=per_round.get)
        rounded = tile("Cost per round", money(each), pct(each, per_round[priciest]), f"Against {priciest.title()} at {money(per_round[priciest])}",
                       f"{cheapest.title()} rounds cost {money(per_round[cheapest])} each.", mark=True)
    else:
        rounded = tile("Cost per round", money(each), 100, "One model is recorded.", "")
    return story + cache + ceiling + rounded


def by_model(rows: list[dict]) -> str:
    """Each model's share of the rounds and of the spend, as two bars and a key."""
    if not rows:
        return card("Spend and rounds by model", '<p class="mean">No round has a cost recorded.</p>')
    models = sorted(by_model_rows(rows).items(), key=lambda kv: -spend(kv[1]))
    total, count = spend(rows), len(rows)
    most, most_rounds = max(models, key=lambda kv: len(kv[1]))
    lead = f"{most.title()} did {pct(len(most_rounds), count):.0f}% of the rounds and {pct(spend(most_rounds), total):.0f}% of the spend."
    rounds_bar = split([(len(rs), f"{m.title()} {len(rs)}", *model_style(m)) for m, rs in models], "Rounds by model")
    spend_bar = split([(spend(rs), f"{m.title()} {money(spend(rs))}", *model_style(m)) for m, rs in models], "Spend by model")
    keys = "".join(f'<span>{swatch(model_style(m)[0])}{esc(m.title())} {len(rs)} rounds, {money(spend(rs))}</span>' for m, rs in models)
    return card("Spend and rounds by model", f'<p class="mean">{esc(lead)}</p><span class="mean">Rounds, {count:,}</span>{rounds_bar}'
                f'<span class="mean">Spend, {money(total)}</span>{spend_bar}<div class="keys">{keys}</div>')


def place(cost: float, scale: float) -> str:
    return f"{100 * cost / scale:.1f}%"


def by_size(landed: list[dict]) -> str:
    """Each size's median and highest landed cost on a lane, with its limit from COST_CEILING as a mark when it has one. L and XL have no limit, so their lane has no mark."""
    lanes, leads = [], []
    for size in SIZES:
        costs = sorted(s["cost"] for s in landed if s["size"] == size)
        if not costs:
            continue
        limit, top, median = agent_loop.COST_CEILING.get(size), costs[-1], cmd_status.median(costs)
        scale = 1.1 * max(limit or 0, top)  # the lane runs 10% past its limit, or past its highest story when it has none
        extra, marks = "", ""
        if limit:
            extra = f", limit {money(limit)}"
            marks = f'<span class="lim" style="left:{place(limit, scale)}"></span><small style="left:{place(limit, scale)}">{money(limit)}</small>'
            leads.append(f"{size} highest story used {pct(top, limit):.0f}% of its limit")
        lanes.append(f'<div class="sizerow"><b style="font-weight:500">{size}</b><div class="lane" aria-label="{size}: median {money(median)}, highest {money(top)}{extra}">'
                     f'<span class="base"></span><span class="rng" style="left:{place(median, scale)};width:{100 * (top - median) / scale:.1f}%"></span>'
                     f'<span class="med" style="left:{place(median, scale)}"></span><span class="hi" style="left:{place(top, scale)}"></span>{marks}'
                     f'<small style="left:{place(median, scale)}">{money(median)}</small><small style="left:{place(top, scale)}">{money(top)}</small></div></div>')
    body = "".join(lanes) or '<p class="mean">No landed story has both a size and a cost recorded.</p>'
    lead = f'<p class="mean">{esc("; ".join(leads))}.</p>' if leads else ""
    keys = ('<div class="keys"><span><span class="sw" style="background:var(--ink);border-radius:50%"></span>Median</span>'
            '<span><span class="sw" style="background:#fff;box-shadow:inset 0 0 0 2px var(--ink);border-radius:50%"></span>Highest</span>'
            '<span><span class="sw" style="background:var(--accent);width:3px"></span>Limit</span></div>')
    return card("Cost per story by size", f"{lead}<div>{body}</div>{keys}")


def routes(rows: list[dict]) -> str:
    """Each reason a model was chosen, as a bar scaled to the most common reason."""
    counted = Counter(str(r["route"]) for r in rows if r.get("route"))
    if not counted:
        return card("Why each model was chosen", '<p class="mean">No round has recorded why its model was chosen.</p>')
    shown = counted.most_common(SHOWN_ROUTES)
    top = shown[0][1]
    lead = f"The most rounds, {top} of {sum(counted.values())}, were routed by {shown[0][0]}."
    lines = "".join(f'<div class="hbar"><span>{esc(why)}</span><span class="b{" top" if i == 0 else ""}" style="width:{pct(n, top):.1f}%"></span><span class="c">{n}</span></div>'
                    for i, (why, n) in enumerate(shown))
    return card("Why each model was chosen", f'<p class="mean">{esc(lead)}</p><div>{lines}</div>')


def token_kinds(rows: list[dict]) -> tuple[dict, float | None]:
    kinds = {"Read from cache": sum(int(r.get("cache_read") or 0) for r in rows), "Written to cache": sum(int(r.get("cache_write") or 0) for r in rows),
             "Written": sum(int(r.get("output") or 0) for r in rows), "Fresh input": sum(int(r.get("input") or 0) for r in rows)}
    all_tokens = sum(kinds.values())
    return kinds, (100 * kinds["Read from cache"] / all_tokens if all_tokens else None)


def tokens(rows: list[dict], kinds: dict, share: float | None) -> str:
    """The tokens-by-kind split bar, its counts, and the starting context."""
    if share is None:
        return card("Tokens", '<p class="mean">No tokens are recorded.</p>')
    all_tokens = sum(kinds.values())
    bar = "".join(f'<span style="flex:{n}" title="{esc(k)}"></span>' for k, n in kinds.items() if n)
    keys = "".join(f'<span>{swatch(TOKEN_COLOR.get(k, ""))}{esc(k)} {n:,}</span>' for k, n in kinds.items())
    starts = [int(r["start_tokens"]) for r in rows if r.get("start_tokens")]
    start = (f"A builder loads {sum(starts) // len(starts):,} tokens of context on average before it starts."
             if starts else "Starting context is not recorded.")
    return card("Tokens", f'<p class="mean">Reading from cache is the cheap path, and it made up {share:.1f}% of {all_tokens:,} tokens.</p>'
                f'<div class="stack" style="height:24px" aria-label="Tokens by kind">{bar}</div><div class="keys">{keys}</div><p class="mean">{esc(start)}</p>')


def priciest(landed: list[dict]) -> str:
    top = sorted(landed, key=lambda s: -s["cost"])[:SHOWN_STORIES]
    if not top:
        return card("Most expensive landed stories", '<p class="mean">No landed story has a cost recorded.</p>')
    lead = f"The most expensive landed story cost {money(top[0]['cost'])}, review included."
    lines = "".join(f'<div class="row"><span class="n">#{esc(s["story"].rsplit("-", 1)[-1])}</span><span class="t">{esc(s["size"] or "size not recorded")}</span>'
                    f'<b>{money(s["cost"])}</b></div>' for s in top)
    return card("Most expensive landed stories", f'<p class="mean">{esc(lead)}</p><div>{lines}</div>')


def read_json(name: str) -> dict:
    try:
        found = json.loads((gh_budget.home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


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
    return card("GitHub budget", "".join(f'<p class="mean">{esc(line)}</p>' for line in lines))


def render(data: dict) -> str:
    """The Cost section as HTML, from the page's figures in DATA."""
    head = '<section class="chap" id="cost" aria-labelledby="c0"><h2 id="c0">Cost</h2>'
    log = data.get("log")
    if log is None:
        return head + '<p class="mean">Cost is not recorded, because the run log could not be read.</p>' + github_budget() + "</section>"
    rows = rounds(log)
    if not rows:
        return head + '<p class="mean">No round is recorded in the run log yet.</p>' + github_budget() + "</section>"
    landed = landed_stories(log)
    paid = cmd_status.priced(rows)  # every cost figure reads these, and the token figures read every round
    kinds, share = token_kinds(rows)
    costs = [s["cost"] for s in landed]
    lead = (f"The run log's rounds cost {money(spend(paid))}" + (f", or {money(sum(costs) / len(costs))} for each landed story" if costs else "") + "."
            if paid else "No round in the run log has a cost recorded.")
    if share is not None:
        lead += f" Caching kept it low: {share:.1f}% of tokens came from cache."
    return (head + f'<p class="read">{esc(lead)}</p><div class="tiles">{tiles(paid, landed, kinds, share)}</div>'
            f'<div class="grid2">{by_model(paid)}{by_size(landed)}{routes(rows)}{tokens(rows, kinds, share)}{priciest(landed)}{github_budget()}</div></section>')
