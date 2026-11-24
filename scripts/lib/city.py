"""OliverCode City's terminal panel (#1097): the commands the owner would type and `olivercode status`'s own live output, read with no model call.

`panel_html(now)` is the terminal-styled panel and the timestamp under it, built from `cmd_status.run`'s own printed lines for the OliverCode
checkout itself -- the same code and the same repo a terminal there would read. It is cached for PANEL_TTL seconds so the page's frequent
automatic rewrites (#990) do not repeat its GitHub reads between them. `status_report._write`, `status_report.write_empty` and `cmd_status.page`
all call it, so the panel shows on the runner's automatic rewrite and on a manual `olivercode status page` alike.
"""

from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import cmd_status, failure_log, repo_state
from lib.local_config import OC_ROOT

PANEL_TTL = 1800  # seconds a cached panel serves a rewrite before `olivercode status` runs again; matches status_report.REWRITE_MINUTES
CD_TARGET = "~/.claude/olivercode"  # the documented, stable path (CLAUDE.md), not OC_ROOT's resolved checkout -- what the owner would actually type
STYLE = (
    ".oc-term{background:#0b0b0c;color:#d8d8d8;font:14px/1.6 ui-monospace,Menlo,Consolas,monospace;"
    "border-radius:8px;padding:16px;margin:16px 0;overflow-x:auto}"
    '.oc-term .cmd{color:#8ab4ff}.oc-term .cmd::before{content:"$ "}'
    ".oc-term pre{margin:8px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:inherit}"
    ".oc-term-stamp{color:#8a8a8a;margin:4px 0 16px;font:14px/1.5 system-ui,sans-serif}"
)


def cache_path() -> Path:
    return failure_log.home() / "city-panel.json"


def status_lines(now: datetime, runner=None) -> list[str]:
    """The lines `olivercode status` prints for the OliverCode checkout itself, from the same code a terminal there would run."""
    lines: list[str] = []
    (runner or cmd_status.run)(repo_state.origin(OC_ROOT), out=lines.append, now=now, folder=OC_ROOT)
    return lines


def _panel_body(now: float, runner=None) -> str:
    printed = "\n".join(html.escape(line) for line in status_lines(datetime.fromtimestamp(now, timezone.utc), runner))
    stamp = html.escape(datetime.fromtimestamp(now).strftime("%A %d %B %Y %H:%M"))
    return (
        f"<div class=\"oc-term\"><style>{STYLE}</style>"
        f'<div class="cmd">cd {html.escape(CD_TARGET)}</div><div class="cmd">olivercode status</div>'
        f"<pre>{printed}</pre></div>"
        f'<p class="oc-term-stamp">{stamp}</p>'
    )


def _load_cache() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def panel_html(now: float | None = None, runner=None) -> str:
    """The terminal panel and the timestamp under it. Cached for PANEL_TTL seconds, so the page's frequent automatic rewrites (#990) spend no
    extra GitHub reads between them."""
    now = time.time() if now is None else now
    cached = _load_cache()
    if cached.get("html") and now - float(cached.get("at", 0)) < PANEL_TTL:
        return cached["html"]
    body = _panel_body(now, runner)
    try:
        failure_log.write_atomic(cache_path(), json.dumps({"at": now, "html": body}))
    except OSError:
        pass
    return body
