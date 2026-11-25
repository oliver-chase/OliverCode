"""OliverCode City's dashboard (#1097, #1177): cards, bars and status marks drawn from the same figures `olivercode status` prints, read with no model call.

`panel_html(now)` is the dashboard for the OliverCode checkout itself, with the two terminal commands in one plain line under it. It is cached for
PANEL_TTL seconds so the page's frequent automatic rewrites (#990) do not repeat their GitHub reads between them. `status_report._write`,
`status_report.write_empty` and `cmd_status.page` all call it, so the dashboard shows on the runner's rewrite and on a manual `olivercode status page`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import briefing, cmd_status, failure_log, repo_state
from lib.local_config import OC_ROOT

PANEL_TTL = 1800  # seconds a cached dashboard serves a rewrite before it is read again; matches status_report.REWRITE_MINUTES


def cache_path() -> Path:
    return failure_log.home() / "city-panel.json"


def _dashboard(now: float, runner=None) -> str:
    """The dashboard fragment for the OliverCode checkout itself, or a short plain note when GitHub could not be read. `runner` stands in for the whole read."""
    when = datetime.fromtimestamp(now, timezone.utc)
    if runner is not None:
        return runner(when)
    slug = repo_state.origin(OC_ROOT)
    rows = cmd_status.recent(slug, when - timedelta(days=cmd_status.DAYS)) if slug else None
    open_now = cmd_status.issue_count.count_issues(slug, "open") if slug else None
    if rows is None or open_now is None:
        return '<p style="color:#5b6472">City could not read GitHub just now, so the figures may be out of date.</p>'
    numbers = cmd_status.four_numbers(when, open_now, rows, cmd_status.run_log(), OC_ROOT)
    snap = cmd_status.gather(slug, when, open_now, rows, numbers, cmd_status.owner_steps(slug), cmd_status._idea_count(), not cmd_status.city_gap())
    return f"<style>{briefing.STYLE}</style>" + briefing.dashboard_html(snap)


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
