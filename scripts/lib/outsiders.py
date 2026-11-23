"""Outsider activity (#826): an issue or pull request by an author outside `allowedAuthors` (olivercode.local.json) reaches the owner queue once, as its reference, author and link without the title.
An empty list switches the check off. A line is never re-queued, open or done, so a closed line stays closed."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

from lib import cmd_owner
from lib.local_config import load_local


def allowed() -> set[str]:
    return {str(a).lower() for a in load_local().get("allowedAuthors", [])}


def recent(slug: str) -> list[dict]:
    """Issues and pull requests open or changed in the last 7 days, through REST."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ran = subprocess.run(["gh", "api", f"repos/{slug}/issues?state=all&since={since}&per_page=100", "--paginate", "--jq", ".[]|tojson"],
                         capture_output=True, text=True, timeout=120)
    return [json.loads(l) for l in ran.stdout.splitlines() if l.strip()] if ran.returncode == 0 else []


def check(boards: list[tuple[str, str]]) -> None:
    """Queue each outsider item of each (name, owner/repo) board that the queue does not already hold."""
    ok = allowed()
    for slug in ([s for _, s in boards] if ok else []):
        for it in recent(slug):
            who, ref = (it.get("user") or {}).get("login") or "unknown", f"{slug}#{it['number']}"
            if who.lower() in ok or any(f"outsider {ref} " in i["step"] for i in cmd_owner.items()):
                continue
            # An outsider writes the title, so the queue, which sessions read, holds only the reference, the author and the link.
            cmd_owner.add("maintain", f"outsider {ref} ({'pull request' if 'pull_request' in it else 'issue'}, {it.get('state')}) by {who}: {it.get('html_url')}")
