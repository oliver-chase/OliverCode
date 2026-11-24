"""Open stories from gh REST with no model call: the priority, owner-gate and rank rules `olivercode drain` shares.

Priority is the "Priority: P0..P3" line of the issue body, else a label such as P1 or "priority: P1". A story is owner-gated only when a label contains "owner"
(owner-action, owner-gate). A GitHub hold skips the reads.
"""

from __future__ import annotations

import json
import re
import subprocess

from lib import gh_budget

BODY_PRIORITY = re.compile(r"^\s*(?:\*\*)?Priority:?(?:\*\*)?\s*(P[0-9])\b", re.IGNORECASE | re.MULTILINE)
LABEL_PRIORITY = re.compile(r"^(?:priority\W*)?(P[0-9])$", re.IGNORECASE)


def priority(issue: dict) -> str:
    """P0..P9 from the body's Priority line, else a label, else an empty string."""
    found = BODY_PRIORITY.search(issue.get("body") or "")
    if found:
        return found.group(1).upper()
    for label in issue.get("labels") or []:
        match = LABEL_PRIORITY.match(str(label.get("name", "") if isinstance(label, dict) else label).strip())
        if match:
            return match.group(1).upper()
    return ""


def owner_gated(issue: dict) -> bool:
    names = [str(l.get("name", "") if isinstance(l, dict) else l) for l in issue.get("labels") or []]
    return any("owner" in n.lower() for n in names)  # a label marks owner work; prose that describes an owner step never gates a story (#1075)


def fetch(slug: str) -> list[dict] | None:
    """Open issues (pull requests left out) through the REST list API, or None on a hold or a failed read."""
    if gh_budget.refusal():
        return None
    done = subprocess.run(["gh", "api", "-X", "GET", f"repos/{slug}/issues", "-f", "state=open", "-f", "per_page=100", "--paginate", "--slurp"],
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        return None
    try:
        pages = json.loads(done.stdout or "[]")
    except ValueError:
        return None
    rows = [r for page in pages for r in (page if isinstance(page, list) else [page])]
    return [r for r in rows if isinstance(r, dict) and "pull_request" not in r]


def rank(issue: dict) -> tuple:
    """Order higher urgency first, then stories that unblock the most work.

    GitHub includes dependency counts in issue responses when available. Older
    responses and tests omit them, so a missing count is safely treated as zero.
    """
    summary = issue.get("issue_dependencies_summary") or {}
    unblocks = summary.get("total_blocking", summary.get("blocking", issue.get("unblocks", 0)))
    try:
        unblocks = int(unblocks or 0)
    except (TypeError, ValueError):
        unblocks = 0
    return (priority(issue) or "P9", -unblocks, issue.get("number", 0))
