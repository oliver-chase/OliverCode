"""When a covered lesson counts as fixed (#662). A covered lesson is verified once its linked story has an implementation record thirty days old and the failure log holds no later line that names it. Standard library only."""

from __future__ import annotations

import re
from datetime import date, timedelta

from lib import failure_log

VERIFY_DAYS = 30


def rule_key(rule: str) -> str:
    """One key for rule text that differs only in case, spacing or a closing period."""
    return re.sub(r"\s+", " ", rule or "").strip().rstrip(".").lower()


def repeats(lesson: dict, since: str, rows=None) -> bool:
    """True when a failure log line after `since` names the lesson by id or by its rule text."""
    rows = failure_log.entries() if rows is None else rows
    rule = rule_key(lesson.get("rule", ""))
    ident = lesson.get("id") or ""
    for when, _repo, gate, reason in rows:
        if when[:10] > since and ((ident and (ident in reason or ident in gate))
                                  or (rule and rule in reason.lower())):
            return True
    return False


def verified(lesson: dict, today: date | None = None, rows=None) -> bool:
    """A lesson whose linked story has an implementation record at least thirty days old, with no later recurrence."""
    try:
        since = date.fromisoformat(lesson["implemented_on"])
    except (KeyError, TypeError, ValueError):
        return False
    if not lesson.get("covered_by") or not lesson.get("implemented_by") or (today or date.today()) - since < timedelta(days=VERIFY_DAYS):
        return False
    return not repeats(lesson, since.isoformat(), rows)
