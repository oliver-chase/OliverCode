"""The story outbox (#554): story requests that wait for GitHub instead of being lost during a hold.

`olivercode story outbox add --repo OWNER/NAME --title T --body TEXT` appends one JSON line to ~/.olivercode/story-outbox.jsonl
(OLIVERCODE_HOME overrides the folder) and files what it can. `flush` creates each waiting issue through `gh` within the shared
budget, in order, and keeps the rest when a hold or a hit limit stops the run. `health` shows the count of unfiled requests.
Standard library only.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, gh_budget, jsonl_store, repo_name_guard


def outbox_file() -> Path:
    return failure_log.home() / "story-outbox.jsonl"


def waiting() -> list[dict]:
    return jsonl_store.read(outbox_file())


def count() -> int:
    return len(waiting())


def _save(items: list[dict]) -> None:
    jsonl_store.save(outbox_file(), items)


def _locked():
    return jsonl_store.locked(outbox_file())


def add(repo: str, title: str, body: str) -> dict:
    """Queue one request. A name of another fleet repo in OliverCode text is replaced, never filed (#853). A story that already waits is not queued twice (#876)."""
    pattern = repo_name_guard._pattern(repo_name_guard.default_names()) if repo_name_guard.is_olivercode(repo) else None
    if pattern:
        title, body = (pattern.sub(repo_name_guard.REPLACEMENT, t) for t in (title, body))
    item = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "repo": repo, "title": title, "body": body}
    with _locked():  # the duplicate check and the append are one step, so two adds of one story queue it once
        for held in waiting():
            if held["repo"] == repo and held["title"] == title:
                return held
        with outbox_file().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item) + "\n")
    return item


def _run_gh(args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def flush(runner=_run_gh) -> tuple[list[tuple[dict, str]], list[dict], str]:
    """Create each waiting issue. Returns (filed with their refs, still waiting, why it stopped). The budget is checked before
    every create, so a hold or a hit limit leaves the rest in the outbox."""
    items = waiting()
    filed, left, why = [], list(items), ""
    for item in items:
        why = gh_budget.refusal() or gh_budget.reserve_write()
        if why:
            break
        ran = runner(["issue", "create", "--repo", item["repo"], "--title", item["title"], "--body", item.get("body", "")])
        found = re.search(r"/issues/(\d+)", ran.stdout or "")
        if ran.returncode or not found:
            err = " ".join((ran.stderr or ran.stdout or "gh issue create failed").split())
            if gh_budget.is_limit(err):
                gh_budget.note_limit(who="story-outbox")
            why = err
            break
        filed.append((item, f"#{found.group(1)}"))
        left.remove(item)
        with _locked():  # save after each create, so a crash before the next one never files this story again
            now = waiting()
            if item in now:
                now.remove(item)
            _save(now)
    with _locked():
        now = waiting()
    return filed, [i for i in now if i in left], why


def _report(filed, left, why) -> None:
    for item, ref in filed:
        print(f"Filed {ref} in {item['repo']}: {item['title']}")
    if left:
        print(f"{len(left)} request(s) wait in {outbox_file()}. Stopped: {why}. Run `olivercode story outbox flush` when the hold lifts.")


def command_story(argv: list[str], runner=_run_gh) -> int:
    usage = "Usage: olivercode story outbox add --repo OWNER/NAME --title TITLE (--body TEXT | --body-file FILE) | flush | show"
    if argv[:1] != ["outbox"] or len(argv) < 2 or argv[1] not in ("add", "flush", "show"):
        print(usage)
        return 2
    action, rest = argv[1], argv[2:]
    if action == "show":
        for item in waiting():
            print(f"{item['repo']}: {item['title']}")
        print(f"{count()} unfiled")
        return 0
    if action == "flush":
        filed, left, why = flush(runner)
        _report(filed, left, why)
        return 1 if left else 0
    opts: dict[str, str] = {}
    i = 0
    while i < len(rest):
        if rest[i] in ("--repo", "--title", "--body", "--body-file") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            print(usage)
            return 2
    body = opts.get("body", "")
    if "body-file" in opts:
        try:
            body = Path(opts["body-file"]).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Cannot read {opts['body-file']}: {exc}")
            return 2
    if not opts.get("repo") or not opts.get("title"):
        print(usage)
        return 2
    reason = repo_name_guard.refusal(f"{opts['title']}\n{body}") if repo_name_guard.is_olivercode(opts["repo"]) else ""
    if reason:
        print(f"Not filed: {reason} Line 1 is the title.")
        return 1
    add(opts["repo"], opts["title"], body)
    filed, left, why = flush(runner)
    _report(filed, left, why)
    return 0
