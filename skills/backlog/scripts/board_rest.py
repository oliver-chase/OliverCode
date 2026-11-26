"""Reads a Project board and a repo's issues through GitHub's REST API, which spends the core budget and leaves the
shared GraphQL budget (`scripts/lib/gh_budget.py`) alone. The results are shaped like the `gh` GraphQL commands'
output, so `check_board_hygiene.py` reads either. Every reader returns None when REST cannot read the target, and the
caller then falls back to the GraphQL command.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

VERSION = ["-H", "X-GitHub-Api-Version: 2022-11-28"]
WANT = ("Status", "Priority", "Size", "Work Type", "Area")
ISSUE_FILTER = '.[] | select(has("pull_request") | not) | {number, state, title}'


def _objects(text: str) -> list:
    return [json.loads(line) for line in (text or "").splitlines() if line.strip()]


def shape(item: dict) -> dict:
    """One REST board item as `gh project item-list --format json` spells it: a field is keyed by its name with a
    lower-case first letter, and `content.repository` is `owner/name`."""
    content = item.get("content") or {}
    out = {"title": content.get("title"),
           "content": {"number": content.get("number"), "title": content.get("title"), "type": item.get("content_type")}}
    # The Title and Repository fields break the REST items endpoint, so both come from the content.
    repo = (content.get("repository") or {}).get("full_name") or "/".join((content.get("repository_url") or "").split("/")[-2:])
    if repo:
        out["content"]["repository"] = repo
    for field in item.get("fields") or []:
        value, name = field.get("value"), field["name"]
        if field["data_type"] == "single_select":
            out[name[0].lower() + name[1:]] = ((value or {}).get("name") or {}).get("raw")
    return out


def project_items(config: dict, run) -> list | None:
    """Every unarchived item of the config's board. `run(args)` returns a command's stdout, or None when it failed."""
    owner, number = config["projectOwner"], config["projectNumber"]
    for kind in ("users", "orgs"):
        base = f"{kind}/{owner}/projectsV2/{number}"
        fields = run(["api", *VERSION, f"{base}/fields?per_page=100", "--paginate", "--jq", ".[]"])
        if fields is None:
            continue
        want = {w.lower() for w in WANT}  # boards spell a field "Work Type" or "Work type"
        ids = ",".join(str(f["id"]) for f in _objects(fields) if f["name"].lower() in want)
        raw = _all_items(run, f"{base}/items", ids)
        if raw is None:
            return None
        return [shape(item) for item in raw if not item.get("archived_at")]
    return None


PAGE, RETRY_PAGE = 100, 25


def _page(run, url: str, size: int, after: str | None, ids: str):
    """One page of items and the cursor of the next, or None when the call failed. The items endpoint pages by the
    `after` cursor in the response's Link header, so the page is read with `-i`."""
    cursor = f"&after={after}" if after else ""
    raw = run(["api", *VERSION, "-i", f"{url}?per_page={size}&fields={ids}{cursor}"])
    if raw is None:
        return None
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    try:
        rows = json.loads(body)
    except ValueError:
        return None
    link = next((line for line in head.splitlines() if line.lower().startswith("link:")), "")
    nxt = re.search(r'<([^>]*)>;\s*rel="next"', link)
    found = nxt and parse_qs(urlparse(nxt.group(1)).query).get("after")
    return rows, (found[0] if found else None)


def _all_items(run, url: str, ids: str) -> list | None:
    """Every item, one cursor page at a time. A page that fails is read again once from the same cursor with a smaller
    page size, and a retry that fails too gives None, so the caller never falls back to the GraphQL read (#1310)."""
    rows: list = []
    after = None
    while True:
        got = _page(run, url, PAGE, after, ids) or _page(run, url, RETRY_PAGE, after, ids)
        if got is None:
            return None
        items, after = got
        rows += items
        if not after:
            return rows


def repo_issues(repo: str, run) -> list | None:
    """Every issue of a repo as {number, state, title}, with state spelled OPEN or CLOSED as `gh issue list` does."""
    raw = run(["api", *VERSION, f"repos/{repo}/issues?state=all&per_page=100", "--paginate", "--jq", ISSUE_FILTER])
    if raw is None:
        return None
    return [{**issue, "state": issue["state"].upper()} for issue in _objects(raw)]
