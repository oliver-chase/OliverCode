"""The status page (#990): one local HTML file the runner rewrites with no model call, and the one small-model call that publishes it to City.

The runner calls `record` when a story starts, lands or is held and when a run begins or ends, and `drain` calls it with a tick at least every
REWRITE_MINUTES while it runs. `record` keeps each repo's run in `status-run.json` and rewrites `status.html` locally with no model call. Publishing
that page to the Claude Artifact URL saved as `cityArtifact` is an explicit owner action; it is never part of a builder lifecycle. The page reloads itself
every REFRESH_SECONDS, and a script in it counts elapsed time from the start and estimate written into it.
"""

from __future__ import annotations

import fcntl
import html
import json
import math
import platform
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import agent_loop, cmd_owner, failure_log, gh_budget, model, repo_state, run_lock
from lib.local_config import load_local

REWRITE_MINUTES = 30
REFRESH_SECONDS = 60
DAYS = 7
PUBLISH_MODEL = "haiku"
DEFAULT_TOKENS = {"bg": "#ffffff", "text": "#000000", "muted": "#595959", "accent": "#1a4fd6", "line": "rgb(0 0 0 / 0.12)"}
DARK_TOKENS = {"bg": "#0f0f10", "text": "#f2f2f2", "muted": "#a6a6a6", "accent": "#8ab4ff", "line": "rgb(255 255 255 / 0.16)"}
TOKEN = re.compile(r"--(bg|text|muted|accent|line)\s*:\s*([^;}\n]+?)\s*;")
OUTSIDE = "outside the runner"  # the model and cost a commit that landed without the runner shows in their place (#996)


def _idle() -> dict:
    """The entry of a repo with landings and no run, so its section still shows what landed (#996)."""
    return {"active": False, "builders": 0, "started": 0, "estimate_min": None, "origin": "", "building": {}, "queue": [], "held": [], "waiting": []}


def page_path() -> Path:
    return failure_log.home() / "status.html"


def state_path() -> Path:
    return failure_log.home() / "status-run.json"


@contextmanager
def _locked():
    """One writer at a time across threads and processes, so concurrent events never overwrite each other's change to `status-run.json`."""
    path = failure_log.home() / "status-run.lock"
    try:
        fh = open(path, "a")
    except OSError:
        yield
        return
    with fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def design_tokens() -> dict:
    """The page's colors: the tokens `--bg`, `--text`, `--muted`, `--accent` and `--line` that the owner's designFile declares (#995), else the shipped standard."""
    found = {}
    path = load_local().get("designFile")
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8") if path else ""
    except OSError:
        text = ""
    for name, value in TOKEN.findall(text):
        found.setdefault(name, value)
    return {**DEFAULT_TOKENS, **found}


def history(log: list[dict], slug: str, now: float, days: int = DAYS) -> list[dict]:
    """The landing rows of SLUG in the last DAYS days, each with its story's tokens and cost summed from the round rows of that story up to the landing."""
    since = now - days * 86400
    rows = [r for r in log if r.get("repo", slug) == slug]
    landings = [r for r in rows if r.get("landed") and _epoch(r.get("at")) >= since]
    out = []
    for land in landings:
        mine = [r for r in rows if str(r.get("story", "")) in (land["story"], land["story"] + "-review") and not r.get("landed") and _epoch(r.get("at")) <= _epoch(land.get("at"))]
        priced = [r["cost_usd"] for r in mine if isinstance(r.get("cost_usd"), (int, float))]
        out.append({**land, "tokens": sum(int(r.get("input") or 0) + int(r.get("output") or 0) for r in mine),
                    "cost": sum(priced) if priced else None, "model": land.get("model") or next((r.get("model") for r in reversed(mine) if r.get("model")), "")})
    return sorted(out, key=lambda r: _epoch(r.get("at")), reverse=True)


def _epoch(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def estimate_minutes(landed: list[dict], stories: int, builders: int) -> int | None:
    """Minutes to finish STORIES on BUILDERS at the mean minutes a story took in the last week, or None when no story has landed in that time."""
    spent = [float(r["minutes"]) for r in landed if isinstance(r.get("minutes"), (int, float))]
    if not spent or stories < 1:
        return None
    return max(1, math.ceil(stories * (sum(spent) / len(spent)) / max(1, builders)))


def thread_message(slug: str, entry: dict, path: Path) -> str:
    """What the thread that started a run says last, and the title it takes in the same turn (#990)."""
    count = len(entry["queue"]) + len(entry["building"])
    plural = "builder" if entry["builders"] == 1 else "builders"
    if entry.get("estimate_min"):
        finish = datetime.fromtimestamp(entry["started"] + entry["estimate_min"] * 60).strftime("%H:%M")
        when = f"Estimate: about {entry['estimate_min']} minutes for {count} stories, finishing near {finish}."
    else:
        when = f"Estimate: none yet, because no story has landed in the last {DAYS} days to time."
    return (f"{when} {entry['builders']} {plural} running.\n"
            f"Status page: {path}, which reloads every {REFRESH_SECONDS} seconds and is rewritten at every landing and at least every {REWRITE_MINUTES} minutes.\n"
            f"Close your reply with those lines and title this thread \"{slug.rsplit('/', 1)[-1]}, {count} building\" in the same turn.")


def record(slug: str, kind: str, issue: dict | None = None, *, origin: str = "", builders: int = 1, queue=(), waiting=(), model_name: str = "",
           now: float | None = None, publisher=None, log=None) -> str:
    """Apply one runner event to SLUG's run and rewrite the local page without a model call. KIND is begin, start, land, held, end or tick.
    Returns the thread message for begin and '' otherwise. A write that fails never stops a run."""
    now = now or time.time()
    with _locked():
        message = _apply(slug, kind, issue, origin, builders, queue, waiting, model_name, now, log)
    # Runner events only write local state and HTML. Publishing a Claude Artifact starts a
    # headless model session, so it is deliberately an explicit owner action via
    # olivercode status publish, never part of a builder's critical path.
    return message


def _apply(slug, kind, issue, origin, builders, queue, waiting, model_name, now, log) -> str:
    state = load_state()
    entry = state.setdefault(slug, {"origin": origin, "builders": builders, "started": now, "estimate_min": None, "active": True,
                                    "building": {}, "queue": [], "held": [], "waiting": []})
    log = log if log is not None else _log()
    n = str(issue["number"]) if issue else ""
    brief = {"n": issue["number"], "title": issue.get("title", "")} if issue else None
    if kind == "begin":
        entry.update(origin=origin, builders=builders, started=now, active=True, building={}, held=[])
    if queue or kind in ("begin", "start"):
        entry["queue"] = [{"n": i["number"], "title": i.get("title", "")} for i in queue if not issue or i["number"] != issue["number"]]
        entry["waiting"] = [{"n": i["number"], "title": i.get("title", "")} for i in waiting]
    if kind == "begin":
        entry["estimate_min"] = estimate_minutes(history(log, slug, now), len(entry["queue"]), builders)
    elif kind == "start" and brief:
        entry["building"][n] = {**brief, "at": now, "model": model_name}
    elif kind in ("land", "held") and brief:
        done = entry["building"].pop(n, None) or {"at": now}
        if kind == "land":
            agent_loop.append_log({"story": f"story-{n}", "repo": slug, "landed": True, "title": brief["title"], "origin": entry["origin"], "model": done.get("model", ""),
                                   "minutes": round((now - float(done["at"])) / 60, 1), "at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            log = _log()
        else:
            entry["held"].append({**brief, "reason": "it stayed open and went back to Ready; its comment holds the reason"})
    elif kind == "end":
        entry["active"], entry["building"] = False, {}
    entry["updated"] = now
    _save(state)
    _write(state, log, now, published=None)  # only an actual city-publish log row advances this timestamp
    return thread_message(slug, entry, page_path()) if kind == "begin" else ""


def _log() -> list[dict]:
    from lib.cmd_status import run_log
    return run_log()


def _save(state: dict) -> None:
    try:
        failure_log.write_atomic(state_path(), json.dumps(state))
    except OSError:
        pass


def _write(state: dict, log: list[dict], now: float, published: float | None = None) -> None:
    try:
        found = log + outside_landings(log, now)
    except (OSError, ValueError, KeyError):  # the read of outside commits is best effort, so the run's own rows still show
        found = log
    try:
        failure_log.write_atomic(page_path(), render(state, found, now, published=_last_publish(log) if published is None else published, panel=_panel(now)))
    except OSError:
        pass


def write_empty(now: float | None = None) -> Path:
    """Write the page with no run yet, so a first install or `olivercode status --open` has a page to show (#996). No panel: a fresh install
    must not spend a live GitHub read before the owner has even registered a repo (#1097)."""
    failure_log.write_atomic(page_path(), render({}, [], now or time.time()))
    return page_path()


def _panel(now: float) -> str:
    """The terminal panel from City's own module (#1097), behind a lazy import since that module imports this one too. Best effort, like
    `publish`: a page must still write without it."""
    try:
        from lib import city
        return city.panel_html(now)
    except Exception:
        return ""


def open_page(run=None, out=print) -> int:
    """Open the status page in the browser, writing an empty one first when none exists (#996). Returns 1 when it cannot be written or opened."""
    path = page_path()
    try:
        if not path.exists():
            write_empty()
        (run or subprocess.run)(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=True)
    except (OSError, subprocess.SubprocessError) as err:
        out(f"Error: the status page at {path} could not be opened: {err}")
        return 1
    out(f"Opened {path}")
    return 0


def fleet_repos() -> list[tuple[str, Path]]:
    """Each repo of the fleet registry and OliverCode itself that has a GitHub origin, as (owner/name, folder) (#996)."""
    from lib.cmd_install import registered_repos
    return [(slug, path) for _, path in registered_repos() if (slug := repo_state.origin(path))]


def main_commits(path: Path, since: datetime) -> list[tuple[int, float]]:
    """(story number, commit time) for each commit on PATH's origin/main since SINCE that names a story as (#N). It reads git only, with no network call (#996)."""
    try:
        done = subprocess.run(["git", "-C", str(path), "log", "origin/main", f"--since={since:%Y-%m-%dT%H:%M:%SZ}", "--format=%ct %s"],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in done.stdout.splitlines() if done.returncode == 0 else []:
        stamp, _, subject = line.partition(" ")
        named = re.findall(r"\(#(\d+)\)", subject)
        if named and stamp.isdigit():
            found.append((int(named[-1]), float(stamp)))
    return found


def _closed(slug: str, since: datetime) -> list[dict] | None:
    from lib import cmd_status
    return cmd_status.recent(slug, since)


def outside_landings(log: list[dict], now: float, repos=None, closed=None) -> list[dict]:
    """The landing rows of stories a commit on a repo's origin/main names, the REST list of closed issues confirms and the run log has no row for. Each row
    shows OUTSIDE for its model and cost. Git is read for every repo, and the REST list only for a repo with such a commit, so a quiet page costs no GitHub call (#996)."""
    since = datetime.fromtimestamp(now - DAYS * 86400, timezone.utc)
    found = []
    for slug, path in (fleet_repos() if repos is None else repos):
        seen = {str(r.get("story")) for r in log if r.get("repo", slug) == slug}
        latest = {}
        for n, stamp in main_commits(path, since):
            if f"story-{n}" not in seen:
                latest[n] = max(stamp, latest.get(n, 0.0))
        if not latest or gh_budget.refusal("rest"):
            continue
        issues = {r.get("number"): r for r in ((closed or _closed)(slug, since) or []) if r.get("closed_at")}
        for n, stamp in latest.items():
            if n in issues:
                found.append({"story": f"story-{n}", "repo": slug, "landed": True, "outside": True, "title": issues[n].get("title", ""), "model": OUTSIDE,
                              "at": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return found


class Raw(str):
    """A table cell that is already HTML."""


def _cell(label: str, value) -> str:
    inner = value if isinstance(value, Raw) else html.escape(str(value))
    return f'<td data-label="{html.escape(label)}">{inner}</td>'


def _table(head: list[str], rows: list[list], none: str) -> str:
    if not rows:
        return f"<p>{html.escape(none)}</p>"
    heads = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(_cell(h, v) for h, v in zip(head, row)) + "</tr>" for row in rows)
    return f"<table><thead><tr>{heads}</tr></thead><tbody>{body}</tbody></table>"


def _money(value) -> str:
    return "not recorded" if value is None else f"${value:.2f}"


def _last_publish(log: list[dict]) -> float:
    return max([_epoch(r.get("at")) for r in log if r.get("story") == "city-publish"] or [0.0])


def publish_total(log: list[dict], now: float) -> tuple[int, float | None]:
    """(tokens, cost) the publish calls spent today, from the run log."""
    today = datetime.fromtimestamp(now).date()
    mine = [r for r in log if r.get("story") == "city-publish" and datetime.fromtimestamp(_epoch(r.get("at"))).date() == today]
    priced = [r["cost_usd"] for r in mine if isinstance(r.get("cost_usd"), (int, float))]
    return sum(int(r.get("input") or 0) + int(r.get("output") or 0) for r in mine), (sum(priced) if priced else None)


def _repo_section(slug: str, entry: dict, log: list[dict], now: float) -> str:
    building = sorted(entry["building"].values(), key=lambda b: b["at"])
    rows = [[f"#{b['n']} {b['title']}", b.get("model") or "unknown", Raw(f'<span data-since="{b["at"]:.0f}">{int((now - b["at"]) // 60)}</span> minutes')] for b in building]
    head = f"<h2>{html.escape(slug)}</h2>"
    live = [f"{len(building)} of {entry['builders']} builders running" if entry["active"] else "The run has ended"]
    finish = ""
    if entry["active"] and entry.get("estimate_min"):
        end = entry["started"] + entry["estimate_min"] * 60
        finish = (f'<p>Estimated finish <span data-end="{end:.0f}">{datetime.fromtimestamp(end):%H:%M}</span>, '
                  f'<span data-left="{end:.0f}"></span> left. Started by {html.escape(entry.get("origin") or "an unnamed command")}.</p>')
    elif entry["active"]:
        finish = f"<p>No estimate yet, because no story landed in the last {DAYS} days to time. Started by {html.escape(entry.get('origin') or 'an unnamed command')}.</p>"
    building_table = _table(["Building now", "Model", "Elapsed"], rows, "No story is building.")  # the browser recounts each data-since cell from its start time
    queue = _table(["Queue, in order", "Story"], [[i + 1, f"#{q['n']} {q['title']}"] for i, q in enumerate(entry["queue"])], "The queue is empty.")
    waits = _table(["Waits on you", "Story"], [["owner action", f"#{w['n']} {w['title']}"] for w in entry["waiting"]], "Nothing waits on you in this repo.")
    held = _table(["Held", "Why"], [[f"#{h['n']} {h['title']}", h["reason"]] for h in entry["held"]], "No story is held.")
    return f"<section>{head}<p>{html.escape(live[0])}.</p>{finish}{building_table}{queue}{held}{waits}{_landed(slug, log, now)}</section>"


def _landed(slug: str, log: list[dict], now: float) -> str:
    rows = history(log, slug, now)
    parts = ["<h3>Landed in the last seven days</h3>"]
    for back in range(DAYS):
        day = (datetime.fromtimestamp(now) - timedelta(days=back)).date()
        mine = [r for r in rows if datetime.fromtimestamp(_epoch(r.get("at"))).date() == day]
        priced = [r["cost"] for r in mine if r["cost"] is not None]
        total = (f"{len(mine)} landed, {sum(r['tokens'] for r in mine):,} tokens, {_money(sum(priced) if priced else None)}" if mine else "nothing landed")
        parts.append(f"<h4>{day:%A %d %B}: {total}</h4>")
        if mine:
            parts.append(_table(["Story", "Started by", "Model", "Tokens", "Cost"],
                                [[f"#{str(r['story']).rsplit('-', 1)[-1]} {r.get('title', '')}", r.get("origin") or "unrecorded",
                                  OUTSIDE if r.get("outside") else r.get("model") or "unknown",
                                  "not recorded" if r.get("outside") else f"{r['tokens']:,}", OUTSIDE if r.get("outside") else _money(r["cost"])] for r in mine], ""))
    return "".join(parts)


def _median(values: list[float]):
    ordered = sorted(values)
    return None if not ordered else (ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2)


def _validation_seconds(now: float) -> dict[str, list[float]]:
    """{local day: run seconds of each validation that day}, from the validation queue's own log."""
    out: dict[str, list[float]] = {}
    try:
        lines = (failure_log.home() / "validate-runs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
            out.setdefault(time.strftime("%Y-%m-%d", time.localtime(float(row["at"]))), []).append(float(row["run"]))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def spend_days(log: list[dict], now: float, chats: dict | None = None, validation: dict | None = None) -> list[dict]:
    """One row per local day of the last DAYS, newest first, with what the desktop chats and the runner's builders read that day and the waste and speed beside it (#1150).
    A builder reads input, cache-read and cache-write tokens in each round. Rows hold no model call and no GraphQL: transcripts, the run log and the validation log."""
    from lib import usage_sessions
    chats = usage_sessions.chat_spend(days=DAYS, now=now) if chats is None else chats
    validation = _validation_seconds(now) if validation is None else validation
    landed: dict[str, list] = {}
    for slug in {r.get("repo") for r in log if r.get("repo")}:
        for row in history(log, slug, now):
            landed.setdefault(time.strftime("%Y-%m-%d", time.localtime(_epoch(row.get("at")))), []).append(row)
    rows = []
    for back in range(DAYS):
        day = time.strftime("%Y-%m-%d", time.localtime(now - back * 86400))
        rounds = [r for r in log if isinstance(r.get("round"), int) and time.strftime("%Y-%m-%d", time.localtime(_epoch(r.get("at")))) == day]
        read = lambda r: sum(int(r.get(k) or 0) for k in ("input", "cache_read", "cache_write"))  # noqa: E731
        builder = sum(read(r) for r in rounds)
        mine = chats.get(day, {"tokens": 0, "calls": 0, "starts": [], "chats": []})
        total = builder + mine["tokens"]
        priced = [r["cost"] for r in landed.get(day, []) if r["cost"] is not None]
        rows.append({"day": day, "chat": mine["tokens"], "builder": builder, "total": total,
                     "cost_per_story": (sum(priced) / len(priced)) if priced else None,
                     "chat_start": _median(mine["starts"]), "builder_start": _median([read(r) for r in rounds if r["round"] == 1]),
                     "limit_share": (sum(1 for r in rounds if r.get("stop") == "max_turns") / len(rounds)) if rounds else None,
                     "api_share": (sum(1 for r in rounds if r.get("stop") == "api_error") / len(rounds)) if rounds else None,
                     "validation": _median(validation.get(day, [])),
                     "top": sorted(mine["chats"], key=lambda c: -c[1])[:3]})
    return rows


def _spend_panel(log: list[dict], now: float) -> str:
    """The spend panel: for each day the tokens desktop chats and runner builders read with each one's share, the cost per landed story, median start sizes, the share of
    rounds that stopped on the turn limit or an API error, the median validation time and the day's three costliest chats (#1150)."""
    try:
        days = spend_days(log, now)
    except (OSError, ValueError):
        return ""
    pct = lambda v: "none" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    count = lambda v: "none" if v is None else f"{v:,.0f}"  # noqa: E731
    parts = ["<h2>Spend by day</h2>"]
    for d in days:
        label = datetime.strptime(d["day"], "%Y-%m-%d").strftime("%A %d %B")
        if not d["total"] and not d["top"]:
            parts.append(f"<h3>{label}: No activity</h3>")
            continue
        share = lambda n: pct(n / d["total"]) if d["total"] else "none"  # noqa: E731
        parts.append(f"<h3>{label}: {d['total']:,} tokens read</h3>")
        parts.append(_table(["Who", "Tokens read", "Share of the day", "Median start tokens"],
                            [["Desktop chats", f"{d['chat']:,}", share(d["chat"]), count(d["chat_start"])],
                             ["Runner builders", f"{d['builder']:,}", share(d["builder"]), count(d["builder_start"])]], ""))
        parts.append(f"<p>Cost per landed story: {_money(d['cost_per_story'])}. Builder rounds stopped on the turn limit: {pct(d['limit_share'])}, on an API error: {pct(d['api_share'])}. "
                     f"Median validation time: {'none' if d['validation'] is None else f'{d['validation']:.0f} seconds'}.</p>")
        if d["top"]:
            parts.append(_table(["Costliest chats", "Tokens read", "Calls", "Average context"],
                                [[name[:8], f"{tokens:,}", f"{calls:,}", f"{tokens // max(1, calls):,}"] for name, tokens, calls in d["top"]], ""))
    return "".join(parts)


SCRIPT = """<script>
(function () {
  var pub = Number(document.body.dataset.published || 0), active = document.body.dataset.active === "1", stale = Number(document.body.dataset.stale) * 60;
  function tick() {
    var now = Date.now() / 1000;
    document.querySelectorAll("[data-since]").forEach(function (el) { el.textContent = Math.max(0, Math.floor((now - Number(el.dataset.since)) / 60)); });
    document.querySelectorAll("[data-left]").forEach(function (el) {
      var left = Math.floor((Number(el.dataset.left) - now) / 60);
      el.textContent = left >= 0 ? left + " minutes" : "0 minutes, " + (-left) + " past the estimate";
    });
    var note = document.getElementById("published");
    if (pub) {
      var ago = Math.floor((now - pub) / 60);
      note.textContent = "Last published " + ago + " minutes ago." + (active && now - pub > stale ? " Warning: this is older than " + (stale / 60) + " minutes while a run is active, so the runner may have stopped." : "");
    }
  }
  tick(); setInterval(tick, 30000);
})();
</script>"""


def render(state: dict, log: list[dict], now: float, published: float = 0.0, panel: str = "") -> str:
    """The whole page as one HTML string. It reads only its arguments. `panel` is City's terminal panel (#1097), already rendered HTML."""
    light = {"bg": "#ffffff", "text": "#17151b", "muted": "#687080", "accent": "#a99be8", "line": "rgb(0 0 0 / 0.10)"}
    vars_ = lambda t: "".join(f"--{k}: {v}; " for k, v in t.items())  # noqa: E731
    state = {k: v for k, v in state.items() if isinstance(v, dict)}  # the `_publish` key holds a word, not a repo
    active = any(e["active"] for e in state.values())
    tokens, cost = publish_total(log, now)
    waiting = _owner_steps()
    slugs = sorted(set(state) | {r["repo"] for r in log if r.get("outside")})  # a repo with a commit that landed outside the runner shows too (#996)
    body = "".join(_repo_section(slug, state.get(slug) or _idle(), log, now) for slug in slugs) or "<p>No run has started on this machine yet.</p>"
    owner = _table(["Step only you can take"], [[f"#{i['id']} {i.get('step', '')}"] for i in waiting], "No owner step is open.")
    spend = f"Publishing City today: {tokens:,} tokens, {_money(cost)}."
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}"><title>OliverCode status</title><style>:root {{ {vars_(light)} }}'
            "body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.65 Georgia, 'Times New Roman', serif; }"
            "main { max-width: 1040px; margin: 0 auto; padding: 32px 24px 76px; }"
            "h1, h2, h3, h4 { color: #17151b; font-family: Georgia, 'Times New Roman', serif; font-weight: 500; line-height: 1.2; } h1 { font-size: clamp(32px, 5vw, 48px); margin: 0 0 12px; } h2 { font-size: 28px; margin: 48px 0 14px; } h3 { font-size: 21px; } h4 { font-size: 17px; }"
            "a { color: #7864c8; } a:focus-visible, summary:focus-visible { outline: 2px solid #a99be8; outline-offset: 3px; }"
            "p { margin: 8px 0; } .muted { color: var(--muted); } .warn { color: var(--accent); }"
            "table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; } th, td { text-align: left; padding: 8px 12px 8px 0; vertical-align: top; border-bottom: 1px solid var(--line); }"
            "th { font-weight: 500; color: var(--muted); }"
            "table { font-size: 14px; } td, th { border-color: var(--line); }"
            "summary { cursor: pointer; padding: 12px 0; color: var(--text); }"
            ".muted, #published { color: var(--muted); } #published { font-size: 13px; }"
            "@media (max-width: 640px) { thead { display: none; } tr, td { display: block; } tr { padding: 8px 0; border-bottom: 1px solid var(--line); } td { border: 0; padding: 2px 0; }"
            "td::before { content: attr(data-label) \": \"; color: var(--muted); } }"
            f'</style></head><body data-published="{published:.0f}" data-active="{1 if active else 0}" data-stale="{run_lock.STALL_MINUTES}"><main>{panel}'
            f'{"" if panel else "<h1>OliverCode City</h1>"}<p id="published" class="warn"></p>'  # the dashboard leads: what needs the owner comes first (#1209, #1177)
            f'<details style="margin-top:32px"><summary>Details by project</summary><p class="muted">This machine: {html.escape(platform.node())}. Last rewritten '
            f'{datetime.fromtimestamp(now):%A %d %B %H:%M}. {html.escape(spend)}</p><h3>Every step waiting on you</h3>{owner}{body}{_spend_panel(log, now)}</details>{SCRIPT}</main></body></html>')


def _owner_steps() -> list[dict]:
    try:
        return [i for i in cmd_owner.items() if i.get("status") == "open"]
    except (OSError, ValueError, KeyError):
        return []


def city_url() -> str:
    return str(load_local().get("cityArtifact") or "")


def publish(now: float | None = None, run=None, probe: bool = False) -> dict:
    """Publish the local page to the City artifact URL with one call on the smallest model and log its tokens and cost. Returns {'ok', 'detail', 'tokens', 'cost_usd'}.
    With no cityArtifact set it does nothing. A publish that fails once marks publishing as not working, so the runner stops paying for calls that cannot land, and
    the finding goes to the owner queue (#990). `probe` forces one attempt."""
    url, state = city_url(), load_state()
    if not url:
        return {"ok": False, "detail": "cityArtifact is not set in olivercode.local.json", "tokens": 0, "cost_usd": None}
    if state.get("_publish") == "failed" and not probe:
        return {"ok": False, "detail": "an earlier publish failed, so none is tried until `olivercode status publish --probe` works", "tokens": 0, "cost_usd": None}
    prompt = (f"Publish the local file {page_path()} to the existing artifact {url} with the Artifact tool, unchanged, and add nothing. "
              "Reply with the word done, or with the one-line reason the call failed.")
    try:
        reply = (run or model.run_cli)(prompt, str(page_path().parent), allowed_tools="Artifact", max_turns=3, session="city-publish", model=PUBLISH_MODEL)
    except (model.ModelError, OSError) as exc:
        reply = {"code": 1, "text": str(exc), "usage": {}, "cost_usd": None}
    agent_loop.log_round("city-publish", 1, PUBLISH_MODEL, reply)
    ok = reply.get("code") == 0 and reply.get("text", "").strip().lower().startswith("done")
    with _locked():
        state = load_state()
        state["_publish"] = "ok" if ok else "failed"
        _save(state)
    if not ok:
        try:
            cmd_owner.add("status-page", f"Publish City: the Artifact tool did not publish headless. The local page at {page_path()} still works.",
                          command="olivercode status publish --probe", error=str(reply.get("text", ""))[:200] or "no reply")
        except (OSError, ValueError, TypeError):
            pass
    usage = reply.get("usage") or {}
    return {"ok": ok, "detail": str(reply.get("text", "")).strip()[:200], "tokens": int(usage.get("input") or 0) + int(usage.get("output") or 0), "cost_usd": reply.get("cost_usd")}
