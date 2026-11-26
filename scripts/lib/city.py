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
    return link + body

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
    if cached.get("html") and now - float(cached.get("at", 0)) < PANEL_TTL:
        return cached["html"]
    body = _dashboard(now, runner)
    try:
        failure_log.write_atomic(cache_path(), json.dumps({"at": now, "html": body}))
    except OSError:
        pass
    return body
