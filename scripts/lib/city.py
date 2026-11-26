"""OliverCode City's dashboard (#1097, #1177): cards, bars and status marks drawn from the same figures `olivercode status` prints, read with no model call.

`panel_html(now)` is the dashboard for the OliverCode checkout itself, with the two terminal commands in one plain line under it. It is cached for
PANEL_TTL seconds so the page's frequent automatic rewrites (#990) do not repeat their GitHub reads between them. `status_report._write`,
`status_report.write_empty` and `cmd_status.page` all call it, so the dashboard shows on the runner's rewrite and on a manual `olivercode status page`.
"""

from __future__ import annotations

import json
from html import escape as html_escape
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import briefing, cmd_status, failure_log, repo_state
from lib.local_config import OC_ROOT

PANEL_TTL = 1800  # seconds a cached dashboard serves a rewrite before it is read again; matches status_report.REWRITE_MINUTES
PANEL_VERSION = 5  # invalidate cached panels after the status renderer's builder-note fix


def cache_path() -> Path:
    return failure_log.home() / "city-panel.json"


def _dashboard(now: float, runner=None) -> str:
    """Dashboard fragment with a direct link to this machine's continuously refreshed page."""
    when = datetime.fromtimestamp(now, timezone.utc)
    if runner is not None:
        body = runner(when)
    else:
        slug = repo_state.origin(OC_ROOT)
        rows = cmd_status.recent(slug, when - timedelta(days=cmd_status.DAYS)) if slug else None
        open_now = cmd_status.issue_count.count_issues(slug, "open") if slug else None
        if rows is None or open_now is None:
            body = '<p class="sub">City could not read GitHub just now, so the figures may be out of date.</p>'
        else:
            numbers = cmd_status.four_numbers(when, open_now, rows, cmd_status.run_log(), OC_ROOT)
            snap = cmd_status.gather(slug, when, open_now, rows, numbers, cmd_status.owner_steps(slug), cmd_status._idea_count(), not cmd_status.city_gap())
            body = f"<style>{briefing.STYLE}</style>" + briefing.dashboard_html(snap)
    from lib import status_report  # local import avoids the status-page/city cycle
    href = status_report.page_path().as_uri()
    link = (f'<div style="margin:0 0 24px;padding:12px 0;border-bottom:1px solid var(--line,#ddd)">'
            f'<a href="{href}" style="display:inline-block;color:inherit;text-decoration:none;border:1px solid currentColor;padding:7px 10px;border-radius:3px;font-weight:600">Open the live local page ↗</a>'
            f'<span style="display:block;color:var(--sub,#666);font-size:.85rem;margin-top:6px">Local file: <code>{html_escape(str(status_report.page_path()))}</code> · refreshes every 60 seconds</span></div>')
    return link + body + _portfolio_html(now)



def _portfolio_html(now: float) -> str:
    """Portfolio view across registered repos, using local run state and run-log history only."""
    from lib import status_report

    try:
        repos = status_report.fleet_repos()
        state = status_report.load_state()
        log = cmd_status.run_log()
    except (OSError, ValueError, KeyError):
        return ""
    slugs = sorted({slug for slug, _ in repos} | {slug for slug in state if not slug.startswith("_")} |
                    {str(row.get("repo")) for row in log if row.get("repo")})
    if not slugs:
        return '<section><h2>Your repositories</h2><p class="section-intro">Register projects with OliverCode to see them together here.</p></section>'
    rows = []
    for slug in slugs:
        entry = state.get(slug) or {}
        active = bool(entry.get("active"))
        running = len(entry.get("building") or {})
        queued = len(entry.get("queue") or [])
        delivered = status_report.history(log, slug, now, days=7)
        count = len(delivered)
        state_label = "Running" if active and running else ("Queued" if queued else ("Active" if active else "Idle"))
        state_class = "good" if active and running else ("info" if queued else "")
        recent = f"{count} delivered in 7 days" if count else "No deliveries recorded this week"
        costs = [float(r["cost"]) for r in delivered if r.get("cost") is not None and not r.get("outside")]
        times = [float(r["minutes"]) for r in delivered if isinstance(r.get("minutes"), (int, float)) and not r.get("outside")]
        average_cost = f"${sum(costs) / len(costs):.2f}/story" if costs else "cost not recorded"
        average_time = f"{sum(times) / len(times):.0f} min/story" if times else "time not recorded"
        detail = status_report._repo_section(slug, entry or status_report._idle(), log, now)
        rows.append(
            f'<details class="repo-card"><summary><span class="repo-name">{html_escape(slug)}</span>'
            f'<span class="pill {state_class}">{state_label}</span>'
            f'<span class="repo-stats">{running} building · {queued} queued · {recent} · {average_cost} · {average_time}</span></summary>'
            f'<div class="repo-expanded">{detail}</div></details>'
        )
    total_running = sum(len((state.get(s) or {}).get("building") or {}) for s in slugs)
    total_queued = sum(len((state.get(s) or {}).get("queue") or []) for s in slugs)
    total_delivered = sum(len(status_report.history(log, s, now, days=7)) for s in slugs)
    return (
        f'<section class="portfolio"><h2>Your repositories</h2>'
        f'<p class="section-intro">A fleet-wide view of recorded runner activity—not GitHub backlog counts. Open a project for its individual story and history.</p>'
        f'<div class="cards portfolio-totals"><div class="card"><div class="label">Building across projects</div><div class="big">{total_running}</div></div>'
        f'<div class="card"><div class="label">Queued in active runs</div><div class="big">{total_queued}</div></div>'
        f'<div class="card"><div class="label">Delivered this week</div><div class="big">{total_delivered}</div></div></div>'
        f'<div class="portfolio-list">{"".join(rows)}</div></section>'
    )


def _load_cache() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def panel_html(now: float | None = None, runner=None) -> str:
    """The dashboard. Cached for PANEL_TTL seconds, so the page's frequent automatic rewrites (#990) spend no extra GitHub reads between them."""
    now = time.time() if now is None else now
    cached = _load_cache()
    if cached.get("version") == PANEL_VERSION and cached.get("html") and now - float(cached.get("at", 0)) < PANEL_TTL:
        return cached["html"]
    body = _dashboard(now, runner)
    try:
        failure_log.write_atomic(cache_path(), json.dumps({"version": PANEL_VERSION, "at": now, "html": body}))
    except OSError:
        pass
    return body
