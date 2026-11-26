"""Where a lesson's story goes and when a covered lesson counts as fixed (#662).

A story request is filed on GitHub only from a checkout whose origin is the repo its own backlog config names.
Any other checkout (a fork carrying the upstream config, or one with no config) writes the request to
docs/BACKLOG.md and creates no issue. A covered lesson is verified once thirty days have passed since it was
covered and the failure log holds no later line that names it. Standard library only.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from lib import failure_log, local_config
from lib.local_config import OC_ROOT

VERIFY_DAYS = 30
SECTION = "## Requested stories"


def own_backlog(slug: str, oc_root: Path | None = None) -> bool:
    """True when the checkout's backlog config names the same owner/repo as its origin remote."""
    try:
        data = local_config.backlog_config(Path(oc_root or OC_ROOT))
        return bool(slug) and slug == f"{data['repoOwner']}/{data['repoName']}"
    except (OSError, ValueError, KeyError, TypeError):
        return False


def rule_key(rule: str) -> str:
    """One key for rule text that differs only in case, spacing or a closing period."""
    return re.sub(r"\s+", " ", rule or "").strip().rstrip(".").lower()


def write_request(req: dict, oc_root: Path | None = None) -> str:
    """Append one story request to docs/BACKLOG.md and return that path as the reference."""
    backlog = Path(oc_root or OC_ROOT) / "docs" / "BACKLOG.md"
    text = backlog.read_text(encoding="utf-8") if backlog.is_file() else "# Backlog\n"
    if SECTION not in text:
        text = text.rstrip("\n") + f"\n\n{SECTION}\n"
    entry = f"\n### {req['title']}\n\n{req['body'].rstrip()}\n"
    backlog.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")
    return "docs/BACKLOG.md"


def repeats(lesson: dict, since: str, rows=None) -> bool:
    """True when a failure log line after `since` names the lesson by id or by its rule text."""
    rows = failure_log.entries() if rows is None else rows
    rule = rule_key(lesson.get("rule", ""))
    for when, _repo, gate, reason in rows:
        if when[:10] > since and (lesson.get("id", "?") in reason or lesson.get("id", "?") in gate
                                  or (rule and rule in reason.lower())):
            return True
    return False


def verified(lesson: dict, today: date | None = None, rows=None) -> bool:
    """A covered lesson with a cover date at least thirty days back and no repeat in the failure log since."""
    try:
        since = date.fromisoformat(lesson["covered_on"])
    except (KeyError, TypeError, ValueError):
        return False
    if not lesson.get("covered_by") or (today or date.today()) - since < timedelta(days=VERIFY_DAYS):
        return False
    return not repeats(lesson, since.isoformat(), rows)
