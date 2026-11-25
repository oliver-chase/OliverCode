#!/usr/bin/env python3
"""Checks the live GitHub Project board for hygiene findings. Never auto-fixes. Needs `gh` on PATH.
`references/project-fields.md` ("Sweep dimensions") states what each dimension checks.

Usage:
    check_board_hygiene.py --config path/to/backlog-config.json                       # every dimension
    check_board_hygiene.py --config CFG --dimension X [--dimension Y]  # only these: fields, drift, duplicates, close-gate, board-reopens, groom
    check_board_hygiene.py --config CFG --verify-config  # stop after the fork and placeholder checks, touching nothing
    check_board_hygiene.py --config CFG --verify-baseline [--fields-file F]  # compare the board's fields with shared/kanban-baseline.json
The config is the `docs/backlog-config.json` of the repo whose board you check. This script only reads.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import check_kanban_baseline as kanban  # noqa: E402
import board_mirror  # noqa: E402
import board_rest  # noqa: E402
import gh_budget  # noqa: E402
import complete_story as cs  # noqa: E402
from log_action import gh_api  # noqa: E402
from board_grooming import WAITING_STATUSES, built_not_moved, epic_moves, epic_rollup, field, overlapping_titles  # noqa: E402

ITEM_LIMIT = 2000

# Every baseline lane except the finished one holds open work (shared/kanban-baseline.json).
REQUIRED_STATUSES = {lane for lane in kanban.load_baseline()["lanes"] if lane.lower() not in {"complete", "done"}}
# The finished column's config key. Every other column, such as Todo or In review, holds open work.
FINISHED_STATUS_KEYS = {"complete", "done"}


def run_gh(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh {' '.join(args)} failed: {result.stderr.strip()}.{kanban.scope_hint(result.stderr) or ' Run `gh auth status` to check the login.'}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def run_gh_soft(args):
    """A gh command's stdout, or None when it failed, so a REST read can fall back to the GraphQL command."""
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def load_items(config, use_cache=True):
    """The board's items from the shared local copy (`scripts/lib/board_mirror.py`), else one live read behind the
    shared budget check."""
    def live():
        refusal = gh_budget.points_refusal()
        if refusal:
            sys.exit(f"The sweep did not run. {refusal} A skipped sweep is not a clean board.")
        return fetch_items(config)
    return board_mirror.read(config["projectOwner"], config["projectNumber"], live, use_cache=use_cache)


def fetch_items(config):
    """The board through REST (core budget), else through `gh project item-list` (GraphQL budget)."""
    items = board_rest.project_items(config, run_gh_soft)
    if items is not None:
        return items
    out = run_gh([
        "project", "item-list", str(config["projectNumber"]),
        "--owner", config["projectOwner"], "--format", "json", "--limit", str(ITEM_LIMIT),
    ])
    items = json.loads(out)["items"]
    if len(items) >= ITEM_LIMIT:
        sys.exit(f"The board returned {len(items)} items, the list limit, so the sweep may be cut short. "
                 "Raise ITEM_LIMIT in check_board_hygiene.py and run again.")
    return items


def resolve_statuses(config, live_names):
    """(finished name, open names) as the board spells them. `live_names` maps option ID to live name.

    Boards name the finished column "Complete" or "Done" and spell "In progress" either way, and a
    config key can differ from the live name, so the option ID decides.
    """
    options = config["fields"].get("status", {}).get("options")
    if not options:
        return "Complete", REQUIRED_STATUSES
    finished = [live_names.get(i, k) for k, i in options.items() if k.lower() in FINISHED_STATUS_KEYS]
    open_names = {live_names.get(i, k) for k, i in options.items() if k.lower() not in FINISHED_STATUS_KEYS}
    return (finished[0] if finished else "Complete"), open_names


def live_status_names(config):
    status = config["fields"].get("status")
    if not status:
        return {}
    out = run_gh([
        "api", "graphql", "-f",
        f'query={{ node(id: "{status["id"]}") {{ ... on ProjectV2SingleSelectField {{ options {{ id name }} }} }} }}',
    ])
    return {o["id"]: o["name"] for o in json.loads(out)["data"]["node"]["options"]}


def check_required_fields(items, config, open_statuses=REQUIRED_STATUSES):
    # Work Type and Area are required only on a board whose config defines the field.
    required = ("priority", "size") + (("work Type",) if "workType" in config["fields"] else ()) \
        + (("area",) if "area" in config["fields"] else ())
    problems = []
    for i in items:
        # A card with no Status is open work too, and its Status is the first gap.
        if i.get("status") and i.get("status") not in open_statuses:
            continue
        c = i.get("content", {})
        num = c.get("number")
        missing = ([] if i.get("status") else ["status"]) + [f for f in required if not field(i, f)]
        if missing:
            problems.append(
                f"#{num} \"{c.get('title', '')[:60]}\" ({i.get('status')}): "
                f"missing {', '.join(missing)}"
            )
    return problems


def status_drift(items, states, repo=None, finished="Complete"):
    """The one drift rule (#853): [(issue number, "close" | "reopen" | "add")] for a repo's cards against its issue states.
    A closed issue's card not at `finished` closes, an open issue's card at `finished` reopens, an open issue with no card is added."""
    cards = {c["number"]: i.get("status") for i in items if (c := i.get("content") or {}).get("number") and (c.get("repository") or repo) == repo}
    return [(n, "close" if s == "CLOSED" else "reopen" if n in cards else "add") for n, s in sorted(states.items())
            if (s == "CLOSED" and n in cards and cards[n] != finished) or (s == "OPEN" and (n not in cards or cards[n] == finished))]


def check_status_drift(items, config, finished="Complete"):
    # Board Status and issue state are two stores; a close or a status edit moves only one of them.
    problems = []
    repos = {i["content"].get("repository") for i in items if i.get("content", {}).get("repository")}
    for repo in sorted(repos):
        issues = board_rest.repo_issues(repo, run_gh_soft)
        if issues is None:
            issues = json.loads(run_gh([
                "issue", "list", "--repo", repo, "--state", "all", "--limit", str(ITEM_LIMIT),
                "--json", "number,state,title",
            ]))
        if len(issues) >= ITEM_LIMIT:
            sys.exit(f"{repo} returned {len(issues)} issues, the list limit, so status drift may be cut short. "
                     "Raise ITEM_LIMIT in check_board_hygiene.py and run again.")
        by_number = {x["number"]: x for x in issues}
        cards = {(i.get("content") or {}).get("number"): i for i in items if (i.get("content") or {}).get("repository") == repo}
        own = repo == f"{config['repoOwner']}/{config['repoName']}"  # only the config's own repo is expected to be fully on this board
        for n, kind in status_drift(items, {n: x["state"] for n, x in by_number.items()}, repo, finished):
            if kind != "add":
                c = cards[n]
                problems.append(f"{repo}#{n} \"{c['content'].get('title', '')[:50]}\": board {c.get('status')}, issue {by_number[n]['state']}")
            elif own:
                problems.append(f"{repo}#{n} \"{by_number[n]['title'][:50]}\": open issue not on the board")
    return problems


def check_duplicate_cards(items):
    # Filing an issue adds a card on its own, so a manual `gh project item-add` afterwards makes a second one,
    # and the two cards then carry different Status values.
    cards = {}
    for i in items:
        c = i.get("content", {})
        if c.get("number"):
            cards.setdefault((c.get("repository"), c["number"]), []).append(i)
    problems = []
    for (repo, num), group in sorted(cards.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if len(group) > 1:
            statuses = sorted({str(i.get("status")) for i in group})
            conflict = ", conflicting Status" if len(statuses) > 1 else ""
            problems.append(f"{repo}#{num}: {len(group)} cards ({', '.join(statuses)}{conflict})")
    return problems


def closed_as_not_planned(repo, number, runner):
    """True when GitHub records the issue as closed not planned. A duplicate is closed that way once its findings moved
    to a surviving story, so it has no evidence comment by design (#1074). Raises RuntimeError on a failed read."""
    result = runner([f"repos/{repo}/issues/{number}", "--jq", ".state_reason"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "gh api failed").strip())
    return result.stdout.strip() == "not_planned"


def unproven_closes(items, config, finished="Complete", runner=gh_api):
    """[(number, title)] for each finished item of the config's own repo numbered at or above `closeGateFromIssue` that
    has no comment holding the line complete_story.py ends its evidence with. A story closed through the REST API,
    `gh issue close` or the web has none, and skipped the QA, live and hook or job checks (#836). An issue closed as not
    planned is a duplicate whose findings moved to a surviving story, so it is skipped (#1074). A null or absent key
    switches the check off, and a failed read exits so a cut-short read can never pass as clean."""
    start = config.get("closeGateFromIssue")
    if start is None:
        return []
    if isinstance(start, bool) or not isinstance(start, int):
        sys.exit(f"closeGateFromIssue must be an issue number or null, not {start!r}")
    own = f"{config['repoOwner']}/{config['repoName']}"
    found = []
    for i in items:
        c = i.get("content", {})
        number = c.get("number")
        if i.get("status") != finished or not number or number < start:
            continue
        if (c.get("repository") or own).lower() != own.lower():
            continue
        if field(i, "work type") == "Epic":  # groom closes an epic once its stories close, with no evidence of its own (#1105)
            continue
        try:
            if closed_as_not_planned(own, number, runner):
                continue
            data, _ = cs.fetch(own, number, runner)
        except (RuntimeError, ValueError) as exc:
            sys.exit(f"cannot read #{number} to check how it closed: {exc}")
        if not cs.closed_by_script(data):
            found.append((number, c.get("title", "")))
    return found


def half_closes(items, states, repo, runner=gh_api):
    """[number] of each OPEN story whose card is In Progress and whose last comment ends with the line complete_story.py closes with (#1202).
    complete_story.py died after that comment and before the close, so the sweep finishes the close. A comment that only quotes the line
    is not its last line, and a story with no such comment is left alone. A failed read exits, so a cut-short read never closes a story."""
    found = []
    for i in items:
        c = i.get("content") or {}
        number = c.get("number")
        if not number or states.get(number) != "OPEN" or i.get("status") != "In Progress" or (c.get("repository") or repo) != repo:
            continue
        result = runner(["--paginate", "--slurp", f"repos/{repo}/issues/{number}/comments"])
        if result.returncode != 0:
            sys.exit(f"cannot read #{number} to check for a half-done close: {(result.stderr or 'gh api failed').strip()}")
        bodies = cs.flatten(json.loads(result.stdout or "[]"))
        if bodies and bodies[-1].rstrip().splitlines()[-1:] == [cs.CLOSE_MARKER]:
            found.append(number)
    return found


def check_close_gate(items, config, finished="Complete", runner=gh_api):
    """The sweep's close-gate finding for each story `unproven_closes` names (#836, #1074), with the fix to run."""
    return [f"#{number} \"{title[:50]}\": closed without complete_story.py. "
            f"Fix: reopen #{number} and run complete_story.py --story {number} --config CONFIG --evidence TEXT"
            for number, title in unproven_closes(items, config, finished, runner)]


EPIC_CHUNK = 25


def is_foreign(item, config):
    """A card whose issue lives in a repo other than the config's own."""
    repo = item.get("content", {}).get("repository")
    return bool(repo) and repo.lower() != f"{config['repoOwner']}/{config['repoName']}".lower()


def open_issue_comments(items, config, runner=run_gh):
    """Comments for the open items still in a waiting lane, the only ones built_not_moved reads.
    Each read is one REST call, so the shared GraphQL budget stays untouched. A card of another repo
    is skipped: its number belongs to that repo, so the lookup here would be a 404."""
    repo = f"{config['repoOwner']}/{config['repoName']}"
    out = {}
    for i in items:
        number = i.get("content", {}).get("number")
        if i.get("status") not in WAITING_STATUSES or not number or is_foreign(i, config):
            continue
        pages = json.loads(runner(["api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/comments"]) or "[]")
        out[number] = [{"body": b} for b in cs.flatten(pages)]
    return out


def epic_summaries(items, config, finished, runner=run_gh):
    """Sub-issue totals for the open epics, read in aliased GraphQL queries of EPIC_CHUNK epics each."""
    own = f'{config["repoOwner"]}/{config["repoName"]}'.lower()
    numbers = [i["content"]["number"] for i in items
               if i.get("content", {}).get("number") and field(i, "work type") == "Epic" and i.get("status") != finished
               and (i["content"].get("repository") or own).lower() == own]
    out = {}
    for start in range(0, len(numbers), EPIC_CHUNK):
        chunk = numbers[start:start + EPIC_CHUNK]
        aliases = " ".join(f"e{n}: issue(number: {n}) {{ subIssuesSummary {{ total completed }} }}" for n in chunk)
        data = json.loads(runner(["api", "graphql", "-f",
            f'query={{ repository(owner: "{config["repoOwner"]}", name: "{config["repoName"]}") {{ {aliases} }} }}']))
        repo_data = data["data"]["repository"]
        for n in chunk:
            summary = repo_data[f"e{n}"]["subIssuesSummary"]
            out[n] = (summary["total"], summary["completed"])
    return out


def check_grooming(items, config, finished, open_statuses, runner=run_gh):
    foreign = [f"{i['content']['repository']}#{i['content']['number']} \"{i['content'].get('title', '')[:50]}\": "
               "card of another repo on this board, skipped by the groom checks"
               for i in items if is_foreign(i, config) and i.get("content", {}).get("number")]
    own = [i for i in items if not is_foreign(i, config)]
    return (foreign + built_not_moved(own, open_issue_comments(own, config, runner))
            + epic_rollup(own, epic_summaries(own, config, finished, runner), finished)
            + overlapping_titles(own, open_statuses))


REOPEN_WINDOW = 10  # seconds between a reopen and the board Status change by the same actor that caused it
EVENT_PAGES = 5  # shortcut: reads the newest 500 repo events only; page further if a sweep runs less than daily


def from_status_change(reopen, events):
    """True when a board Status change by the reopen's actor on the same issue sits within REOPEN_WINDOW seconds."""
    when = datetime.fromisoformat(reopen["created_at"].replace("Z", "+00:00"))
    for e in events:
        if (e.get("event") == "project_v2_item_status_changed" and e.get("issue", {}).get("number") == reopen["issue"]["number"]
                and (e.get("actor") or {}).get("login") == (reopen.get("actor") or {}).get("login")
                and abs((datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) - when).total_seconds()) <= REOPEN_WINDOW):
            return True
    return False


def check_board_reopens(config, read=run_gh_soft):
    """Open issues whose last reopen came from a board Status change, with the date. One REST read per page."""
    own = f"{config['repoOwner']}/{config['repoName']}"
    events = []
    for page in range(1, EVENT_PAGES + 1):
        out = read(["api", f"repos/{own}/issues/events?per_page=100&page={page}"])
        if out is None:
            return ["the repo's issue events were not read, so reopens were not checked"]
        rows = json.loads(out or "[]")
        events.extend(rows)
        if len(rows) < 100:
            break
    last = {}
    for e in events:  # newest first, so the first reopen seen per issue is its last
        if e.get("event") == "reopened" and e.get("issue"):
            last.setdefault(e["issue"]["number"], e)
    return [f"#{n} \"{e['issue'].get('title', '')[:50]}\": reopened by a board Status change on {e['created_at'][:10]}"
            for n, e in sorted(last.items())
            if e["issue"].get("state") == "open" and from_status_change(e, events)]


def placeholder_values(config):
    """True when the config still holds the example's placeholder values."""
    text = json.dumps(config)
    return "your-github-org-or-user" in text or '"..."' in text or '"PVT_..."' in text


def origin_slug(folder):
    """owner/repo of the git origin for `folder`, or None when it is no repo or has no origin."""
    result = subprocess.run(["git", "-C", str(folder), "remote", "get-url", "origin"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", result.stdout.strip())
    return match.group(1).lower() if match else None


def verify_config(config, path):
    """Stop a run that would reach a Project this checkout does not own. Two cases are refused:
    a config that still holds placeholders, and a config whose repo is not the git origin of the
    folder it sits in, which is what a fork inherits from the owner."""
    if placeholder_values(config):
        sys.exit(f"{path} still holds the example's placeholder values, so it names no Project. "
                 "Fill in your own repo, Project and field IDs (the field-list command is in "
                 "references/project-fields.md) and run again.")
    named = f"{config['repoOwner']}/{config['repoName']}".lower()
    origin = origin_slug(Path(path).resolve().parent)
    if origin and origin != named:
        sys.exit(f"{path} names {config['repoOwner']}/{config['repoName']}'s Project, but this checkout's origin is "
                 f"{origin}, so this is a fork carrying the owner's config. Nothing was read or written. "
                 "Copy shared/backlog-config.example.json to your own config, fill in your own Project, "
                 "and pass that path.")


def missing_lanes(config):
    """Baseline lanes the config's status options do not list."""
    have = {k.lower() for k in config.get("fields", {}).get("status", {}).get("options", {})}
    return [lane for lane in kanban.load_baseline()["lanes"] if lane.lower() not in have]


def load_config(path):
    """The repo's backlog config. A missing path exits with one line that says where the file lives
    and names the example a fork starts from. The example is never used as a live config."""
    if path is None or not Path(path).is_file():
        sys.exit(f"backlog config not found ({path}). Pass --config with the path to docs/backlog-config.json "
                 "of the repo whose board you check. A fork has no such file of its own: copy "
                 "shared/backlog-config.example.json, fill in your own Project and pass that path. "
                 "The example holds placeholders only, so nothing runs against it.")
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    verify_config(config, path)
    return config


DIMENSIONS = ["fields", "drift", "duplicates", "groom", "close-gate", "board-reopens"]


def wanted(selected, name):
    """True when no --dimension was given or `name` is one of those given."""
    return not selected or name in selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", action="append", choices=DIMENSIONS,
                        help="run only this dimension; repeat the flag to run several")
    parser.add_argument("--config", type=Path, help="path to the repo's docs/backlog-config.json (required)")
    parser.add_argument("--verify-baseline", action="store_true",
                        help="compare the board's field list with shared/kanban-baseline.json, then stop")
    parser.add_argument("--fields-file", type=Path,
                        help="with --verify-baseline: field list JSON from `gh project field-list --format json`; without it gh is read")
    parser.add_argument("--no-cache", action="store_true",
                        help="read the board live instead of reusing a list under 10 minutes old")
    parser.add_argument("--verify-config", action="store_true",
                        help="check the config is placeholder-free and belongs to this checkout, then stop")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.verify_config:
        print(f"{args.config}: names {config['repoOwner']}/{config['repoName']}, Project {config['projectNumber']}.")
        absent = missing_lanes(config)
        if absent:
            print(f"The config lists no status option for {', '.join(absent)}. Run --verify-baseline to compare the board.")
        return
    if args.verify_baseline:
        fields = json.loads(args.fields_file.read_text(encoding="utf-8")) if args.fields_file \
            else kanban.read_fields_from_gh(config)
        sys.exit(1 if kanban.run(fields, config) else 0)
    items = load_items(config, use_cache=not args.no_cache)
    finished, open_statuses = resolve_statuses(config, live_status_names(config))

    checks = []
    if wanted(args.dimension, "fields"):
        checks.append(("required-fields", lambda: check_required_fields(items, config, open_statuses)))
    if wanted(args.dimension, "drift"):
        checks.append(("status-drift", lambda: check_status_drift(items, config, finished)))
    if wanted(args.dimension, "duplicates"):
        checks.append(("duplicate-cards", lambda: check_duplicate_cards(items)))
    if wanted(args.dimension, "close-gate"):
        checks.append(("close-gate", lambda: check_close_gate(items, config, finished)))
    if wanted(args.dimension, "board-reopens"):
        checks.append(("board-reopens", lambda: check_board_reopens(config)))
    if wanted(args.dimension, "groom"):
        checks.append(("groom", lambda: check_grooming(items, config, finished, open_statuses)))

    all_problems = []
    for name, fn in checks:
        problems = fn()
        all_problems.extend(f"[{name}] {p}" for p in problems)
        if not problems:
            print(f"{name}: clean.")

    if all_problems:
        print(f"\n{len(all_problems)} finding(s) (advisory -- read and judge, never auto-fixed):")
        for p in all_problems:
            print(f"  - {p}")
        sys.exit(1)


if __name__ == "__main__":
    main()
