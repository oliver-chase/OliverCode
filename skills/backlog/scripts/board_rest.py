"""Reads a Project board and a repo's issues through GitHub's REST API, which spends the core budget and leaves the
shared GraphQL budget (`scripts/lib/gh_budget.py`) alone. The results are shaped like the `gh` GraphQL commands'
output, so `check_board_hygiene.py` reads either. Every reader returns None when REST cannot read the target, and the
caller then falls back to the GraphQL command.
"""

from __future__ import annotations

import json

VERSION = ["-H", "X-GitHub-Api-Version: 2022-11-28"]
WANT = ("Title", "Status", "Priority", "Size", "Work Type", "Area", "Repository")
ISSUE_FILTER = '.[] | select(has("pull_request") | not) | {number, state, title}'


def _objects(text: str) -> list:
    return [json.loads(line) for line in (text or "").splitlines() if line.strip()]


def shape(item: dict) -> dict:
    """One REST board item as `gh project item-list --format json` spells it: a field is keyed by its name with a
    lower-case first letter, and `content.repository` is `owner/name`."""
    content = item.get("content") or {}
    out = {"content": {"number": content.get("number"), "title": content.get("title"), "type": item.get("content_type")}}
    for field in item.get("fields") or []:
        value, name = field.get("value"), field["name"]
        if field["data_type"] == "title":
            out["title"] = (value or {}).get("raw")
        elif field["data_type"] == "single_select":
            out[name[0].lower() + name[1:]] = ((value or {}).get("name") or {}).get("raw")
        elif field["data_type"] == "repository" and value:
            out["content"]["repository"] = value.get("full_name")
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
        raw = run(["api", *VERSION, f"{base}/items?per_page=100&fields={ids}", "--paginate", "--jq", ".[]"])
        if raw is None:
            return None
        return [shape(item) for item in _objects(raw) if not item.get("archived_at")]
    return None


def repo_issues(repo: str, run) -> list | None:
    """Every issue of a repo as {number, state, title}, with state spelled OPEN or CLOSED as `gh issue list` does."""
    raw = run(["api", *VERSION, f"repos/{repo}/issues?state=all&per_page=100", "--paginate", "--jq", ISSUE_FILTER])
    if raw is None:
        return None
    return [{**issue, "state": issue["state"].upper()} for issue in _objects(raw)]
