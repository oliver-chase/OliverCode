"""The candidates list (#895): gaps the automatic filers find wait here until the owner promotes them to the board.

Gap sweep, retro, audit and maintain call `add`, which appends one JSON line to ~/.olivercode/candidates.jsonl
(OLIVERCODE_HOME overrides the folder) and files nothing. `olivercode candidates` prints the list. `olivercode candidates promote N...`
queues each chosen story in the story outbox and flushes it, so a promoted candidate is filed once. Standard library only.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, repo_name_guard, story_outbox

USAGE = "Usage: olivercode candidates [add --source NAME --repo OWNER/NAME --title TITLE (--body TEXT | --body-file FILE) | promote N... | promote --all | drop N...]"


# The open stories a repo may hold before the automatic filers add none, and how many stories one `retro --auto` run may
# file (#875). limits.json in the OliverCode home folder overrides either number.
DEFAULT_LIMITS = {"openStoryCap": 20, "retroFilesPerRun": 3}


def limits() -> dict:
    """The filing limits, with any number named in limits.json in the OliverCode home folder in place of its default."""
    out = dict(DEFAULT_LIMITS)
    try:
        custom = json.loads((failure_log.home() / "limits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(custom, dict):
        out.update({k: v for k, v in custom.items() if k in out and isinstance(v, (int, float)) and v > 0})
    return out


def candidates_file() -> Path:
    return failure_log.home() / "candidates.jsonl"


def items() -> list[dict]:
    p = candidates_file()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("repo") and item.get("title"):
            out.append(item)
    return out


def count() -> int:
    return len(items())


def _save(rows: list[dict]) -> None:
    p = candidates_file()
    if not rows:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)


@contextmanager
def _locked():
    candidates_file().parent.mkdir(parents=True, exist_ok=True)
    with candidates_file().with_suffix(".lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def has(repo: str, title: str) -> bool:
    """True when the same story already waits here or in the story outbox."""
    return any(i["repo"] == repo and i["title"] == title for i in items() + story_outbox.waiting())


def add(source: str, repo: str, title: str, body: str) -> dict:
    """Append one candidate and file nothing. A candidate that already waits is not added twice."""
    with _locked():
        for held in items():
            if held["repo"] == repo and held["title"] == title:
                return held
        item = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source, "repo": repo, "title": title, "body": body}
        with candidates_file().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item) + "\n")
    return item


def promote(numbers: list[int], runner=story_outbox._run_gh) -> tuple[list[tuple[dict, str]], list[dict], str]:
    """Move the chosen candidates (numbered from 1 as `olivercode candidates` prints them) to the board through the story outbox.

    A candidate leaves the list once the outbox holds it, so a hold or a hit limit never files it twice. Returns what flush reported."""
    with _locked():
        rows = items()
        chosen = [rows[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(rows)]
        for item in chosen:
            story_outbox.add(item["repo"], item["title"], item.get("body", ""))
        _save([r for r in rows if r not in chosen])
    return story_outbox.flush(runner)


def drop(numbers: list[int]) -> int:
    with _locked():
        rows = items()
        gone = {n for n in numbers if 1 <= n <= len(rows)}
        _save([r for i, r in enumerate(rows, 1) if i not in gone])
    return len(gone)


def _numbers(args: list[str]) -> list[int] | None:
    if args == ["--all"]:
        return list(range(1, count() + 1))
    try:
        return [int(a) for a in args] if args else None
    except ValueError:
        return None


def command_candidates(argv: list[str], runner=story_outbox._run_gh) -> int:
    if not argv:
        rows = items()
        for n, item in enumerate(rows, 1):
            print(f"{n}. [{item.get('source', '?')}] {item['repo']}: {item['title']}")
        print(f"{len(rows)} candidate(s)." + (" Run `olivercode candidates promote N` to file one on the board." if rows else ""))
        return 0
    action, rest = argv[0], argv[1:]
    if action in ("promote", "drop"):
        nums = _numbers(rest)
        if nums is None or not all(1 <= n <= count() for n in nums):
            print(f"Name candidate numbers from `olivercode candidates` (1 to {count()}). {USAGE}")
            return 2
        if action == "drop":
            print(f"Dropped {drop(nums)} candidate(s).")
            return 0
        filed, left, why = promote(nums, runner)
        story_outbox._report(filed, left, why)
        return 1 if left else 0
    if action != "add":
        print(USAGE)
        return 2
    opts: dict[str, str] = {}
    i = 0
    while i < len(rest):
        if rest[i] in ("--source", "--repo", "--title", "--body", "--body-file") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            print(USAGE)
            return 2
    body = opts.get("body", "")
    if "body-file" in opts:
        try:
            body = Path(opts["body-file"]).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Cannot read {opts['body-file']}: {exc}")
            return 2
    if not opts.get("repo") or not opts.get("title"):
        print(USAGE)
        return 2
    reason = repo_name_guard.refusal(f"{opts['title']}\n{body}") if repo_name_guard.is_olivercode(opts["repo"]) else ""
    if reason:
        print(f"Not added: {reason} Line 1 is the title.")
        return 1
    add(opts.get("source", "manual"), opts["repo"], opts["title"], body)
    print(f"Added a candidate. {count()} wait in {candidates_file()}.")
    return 0
