#!/usr/bin/env python3
"""Checks the live GitHub Project board for hygiene findings. Never auto-fixes. Needs `gh` on PATH.
`backlog/SKILL.md` states what each dimension checks.

Usage:
    check_board_hygiene.py --config path/to/backlog-config.json                       # every dimension but area
    check_board_hygiene.py --config CFG --skills-root DIR                             # adds area-freshness against DIR's folders
    check_board_hygiene.py --config CFG --dimension X [--dimension Y]  # only these: fields, drift, duplicates, ready, area, suggest, stale, qa-signoff
    check_board_hygiene.py --config CFG --verify-config  # stop after the fork and placeholder checks, touching nothing
    check_board_hygiene.py --config CFG --verify-baseline [--fields-file F]  # compare the board's fields with shared/kanban-baseline.json
The config is the `docs/backlog-config.json` of the repo whose board you check. This script only reads.
"""

import argparse
import json
import datetime
import re
import subprocess
import sys
from pathlib import Path

import check_kanban_baseline as kanban
import check_qa_signoff as qa

# The config's `areaPolicy` names the Area options that match no folder:
#   retired   - frozen labels on Complete items, for families that no longer exist
#   parked    - a family with no folder here whose open items keep the label
#   catchAll  - not a folder: the value for cross-family work
# A config without `areaPolicy` has none of them.
AREA_POLICY_KEYS = ("retired", "parked", "catchAll")

# How long an item may sit without a comment before the stale dimension reports it.
STALE_BACKLOG_DAYS = 14        # P0 and P1 items in Backlog
STALE_IN_PROGRESS_DAYS = 7     # items in In Progress
STALE_DEFERRED_DAYS = 30       # items labelled "deferred"
ITEM_LIMIT = 2000

# Every baseline lane except the finished one holds open work (shared/kanban-baseline.json).
REQUIRED_STATUSES = {lane for lane in kanban.load_baseline()["lanes"] if lane.lower() not in {"complete", "done"}}
# The finished column's config key. Every other column, such as Todo or In review, holds open work.
FINISHED_STATUS_KEYS = {"complete", "done"}

# A keyword scan for "reads as blocked". It misses any phrasing not listed, so a human reads each candidate.
BLOCKED_PHRASES = (
    "not decided", "open design question", "design decision", "owner's call", "deferred",
    "needs a real decision", "ask before", "flag for whenever",
)
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
SIZE_ORDER = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}


def run_gh(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh {' '.join(args)} failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def load_items(config):
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
        if i.get("status") not in open_statuses:
            continue
        c = i.get("content", {})
        num = c.get("number")
        missing = [f for f in required if not i.get(f)]
        if missing:
            problems.append(
                f"#{num} \"{c.get('title', '')[:60]}\" ({i.get('status')}): "
                f"missing {', '.join(missing)}"
            )
    return problems


def check_status_drift(items, config, finished="Complete"):
    # Board Status and issue state are two stores; a close or a status edit moves only one of them.
    problems = []
    repos = {i["content"].get("repository") for i in items if i.get("content", {}).get("repository")}
    for repo in sorted(repos):
        issues = json.loads(run_gh([
            "issue", "list", "--repo", repo, "--state", "all", "--limit", str(ITEM_LIMIT),
            "--json", "number,state,title",
        ]))
        if len(issues) >= ITEM_LIMIT:
            sys.exit(f"{repo} returned {len(issues)} issues, the list limit, so status drift may be cut short. "
                     "Raise ITEM_LIMIT in check_board_hygiene.py and run again.")
        by_number = {x["number"]: x for x in issues}
        on_board = set()
        for i in items:
            c = i.get("content", {})
            if c.get("repository") != repo or c.get("number") not in by_number:
                continue
            on_board.add(c["number"])
            closed = by_number[c["number"]]["state"] == "CLOSED"
            if (i.get("status") == finished) != closed:
                problems.append(
                    f"{repo}#{c['number']} \"{c.get('title', '')[:50]}\": board {i.get('status')}, "
                    f"issue {by_number[c['number']]['state']}"
                )
        # Only the config's own repo is expected to be fully on this board.
        if repo == f"{config['repoOwner']}/{config['repoName']}":
            for n, x in sorted(by_number.items()):
                if x["state"] == "OPEN" and n not in on_board:
                    problems.append(f"{repo}#{n} \"{x['title'][:50]}\": open issue not on the board")
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


def check_ready_occupancy(items):
    # An empty Ready column is correct when no Backlog item is waiting to be queued.
    ready = [i for i in items if i.get("status") == "Ready"]
    if not ready and any(i.get("status") == "Backlog" for i in items):
        return ["Ready column is empty -- nothing queued as next-up work"]
    return []


def discover_families(root):
    # A family is any folder directly under the fleet root. Skills sit inside it, so no deeper walk is needed.
    return {
        d.name for d in Path(root).iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "docs"
    }


def area_policy(config):
    """(retired, parked, catch-all) Area option names from the config's `areaPolicy`."""
    policy = config.get("areaPolicy", {})
    return tuple(set(policy.get(k, [])) for k in AREA_POLICY_KEYS)


def check_area_freshness(config, skills_root):
    live_families = discover_families(skills_root)
    # The config holds only IDs. An option can be renamed in the GitHub UI, so read the live names.
    out = run_gh([
        "api", "graphql", "-f",
        f'query={{ node(id: "{config["fields"]["area"]["id"]}") '
        f'{{ ... on ProjectV2SingleSelectField {{ options {{ name }} }} }} }}',
    ])
    live_options = {
        o["name"] for o in json.loads(out)["data"]["node"]["options"]
    }
    retired, parked, catch_all = area_policy(config)
    known_good = live_families | retired | parked | catch_all
    problems = []
    for opt in sorted(live_options - known_good):
        problems.append(
            f"Area option '{opt}' matches no live family folder and is not among the config's "
            f"retired, parked or catch-all options -- possibly stale"
        )
    for fam in sorted(live_families - live_options):
        problems.append(f"Live family folder '{fam}' has no matching Area option")
    return problems


def check_ready_candidates(items):
    """Fires only when Ready is empty. Needs bodies fetched onto `items` first. Whitespace is
    collapsed before matching, so a phrase that spans a wrapped line still matches."""
    if any(i.get("status") == "Ready" for i in items):
        return []
    if not any(i.get("status") == "Backlog" for i in items):
        return []
    candidates = []
    for i in items:
        if i.get("status") != "Backlog":
            continue
        c = i.get("content", {})
        body = re.sub(r"\s+", " ", (c.get("body") or "")).lower()
        if any(phrase in body for phrase in BLOCKED_PHRASES):
            continue
        candidates.append(i)
    if not candidates:
        return ["Ready is empty and no unblocked Backlog candidate was found -- "
                "every Backlog item reads as blocked by this heuristic, or the heuristic missed a real one"]
    candidates.sort(key=lambda i: (
        PRIORITY_ORDER.get(i.get("priority"), 9),
        SIZE_ORDER.get(i.get("size"), 9),
    ))
    problems = []
    for i in candidates[:5]:
        c = i.get("content", {})
        problems.append(
            f"suggest #{c.get('number')} \"{c.get('title', '')[:60]}\" "
            f"({i.get('priority')}, {i.get('size')}) -- read it, then promote if genuinely unblocked"
        )
    return problems


def fetch_issue_details(config, items, finished="Complete"):
    """item-list's own JSON has no body, label or date. Read every open issue of each repo on the board
    through the paginated REST API, and fill body, created_at, labels and last_comment_at onto the items.
    A failed call exits, so a cut-short read can never pass as a clean sweep."""
    open_items = [i for i in items if i.get("status") != finished]
    if not open_items:
        return
    repos = {i.get("content", {}).get("repository") for i in open_items}
    repos.discard(None)
    repos.add(f"{config['repoOwner']}/{config['repoName']}")
    details = {}
    for repo in sorted(repos):
        rows = gh_pages(f"repos/{repo}/issues?state=open&per_page=100",
                        '.[] | select(.pull_request == null) | '
                        '{number, body, created_at, labels: [.labels[].name]}')
        for row in rows:
            row["last_comment_at"] = None
            details[(repo, row["number"])] = row
        for row in gh_pages(f"repos/{repo}/issues/comments?per_page=100",
                            ".[] | {issue: (.issue_url | split(\"/\") | last | tonumber), at: .created_at}"):
            d = details.get((repo, row["issue"]))
            if d and (d["last_comment_at"] is None or row["at"] > d["last_comment_at"]):
                d["last_comment_at"] = row["at"]
    for i in open_items:
        c = i.get("content", {})
        d = details.get((c.get("repository") or f"{config['repoOwner']}/{config['repoName']}", c.get("number")))
        if d:
            c["body"] = d["body"]
            c["created_at"] = d["created_at"]
            c["labels"] = d["labels"]
            c["last_comment_at"] = d["last_comment_at"]


def gh_pages(endpoint, jq):
    """Every row of a paginated REST list, one JSON object per line from `jq`."""
    out = run_gh(["api", "--paginate", endpoint, "--jq", jq])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def parse_time(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))


def check_stale(items, now=None, finished="Complete"):
    """Backlog P0/P1 items quiet for 14 days, In Progress items quiet for 7, deferred items quiet for 30.
    Needs details fetched onto `items` first. Quiet means no comment, or no filing date when none exists."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    problems = []
    for i in items:
        status = (i.get("status") or "")
        if status == finished:
            continue
        c = i.get("content", {})
        last = c.get("last_comment_at") or c.get("created_at")
        if not last:
            continue
        days = (now - parse_time(last)).days
        label = f"#{c.get('number')} \"{c.get('title', '')[:50]}\" ({status}): no comment in {days} days"
        if status == "Backlog" and i.get("priority") in ("P0", "P1") and days >= STALE_BACKLOG_DAYS:
            problems.append(f"{label}, limit {STALE_BACKLOG_DAYS} for a {i.get('priority')} in Backlog")
        elif status.lower() == "in progress" and days >= STALE_IN_PROGRESS_DAYS:
            problems.append(f"{label}, limit {STALE_IN_PROGRESS_DAYS} for In Progress")
        elif "deferred" in c.get("labels", []) and days >= STALE_DEFERRED_DAYS:
            problems.append(f"{label}, limit {STALE_DEFERRED_DAYS} for a deferred item")
    return problems


def check_qa_signoff(items, config, finished="Complete", runner=qa.gh_api):
    """Every finished item of the config's own repo numbered at or above `qaRequiredFromIssue` needs an
    accepted independent QA sign-off (check_qa_signoff.check). A null or absent key switches the
    dimension off. Comments come through `runner`, the REST runner `qa.fetch` takes, and a failed read
    exits so a cut-short read can never pass as clean."""
    start = config.get("qaRequiredFromIssue")
    if start is None:
        return []
    if isinstance(start, bool) or not isinstance(start, int):
        sys.exit(f"qaRequiredFromIssue must be an issue number or null, not {start!r}")
    own = f"{config['repoOwner']}/{config['repoName']}"
    problems = []
    for i in items:
        c = i.get("content", {})
        number = c.get("number")
        if i.get("status") != finished or not number or number < start:
            continue
        repo = c.get("repository") or own
        if repo.lower() != own.lower():
            continue
        try:
            data, body = qa.fetch(repo, number, runner)
        except (RuntimeError, ValueError) as exc:
            sys.exit(f"cannot read #{number} to check its QA sign-off: {exc}")
        ok, lines = qa.check(qa.flatten(data), body)
        if not ok:
            problems.append(f"#{number} \"{c.get('title', '')[:50]}\" ({finished}): no accepted QA sign-off: {'; '.join(lines)}")
    return problems


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


DIMENSIONS = ["fields", "drift", "duplicates", "ready", "area", "suggest", "stale", "qa-signoff"]


def wanted(selected, name):
    """True when no --dimension was given or `name` is one of those given."""
    return not selected or name in selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", action="append", choices=DIMENSIONS,
                        help="run only this dimension; repeat the flag to run several")
    parser.add_argument("--config", type=Path, help="path to the repo's docs/backlog-config.json (required)")
    parser.add_argument(
        "--skills-root", type=Path,
        help="folder whose direct sub-folders are the Area options' families; area-freshness runs only with it",
    )
    parser.add_argument("--verify-baseline", action="store_true",
                        help="compare the board's field list with shared/kanban-baseline.json, then stop")
    parser.add_argument("--fields-file", type=Path,
                        help="with --verify-baseline: field list JSON from `gh project field-list --format json`; without it gh is read")
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
    items = load_items(config)
    finished, open_statuses = resolve_statuses(config, live_status_names(config))

    checks = []
    skipped = []
    if wanted(args.dimension, "fields"):
        checks.append(("required-fields", lambda: check_required_fields(items, config, open_statuses)))
    if wanted(args.dimension, "drift"):
        checks.append(("status-drift", lambda: check_status_drift(items, config, finished)))
    if wanted(args.dimension, "duplicates"):
        checks.append(("duplicate-cards", lambda: check_duplicate_cards(items)))
    if wanted(args.dimension, "ready"):
        checks.append(("ready-occupancy", lambda: check_ready_occupancy(items)))
    if wanted(args.dimension, "area"):
        if args.skills_root and "area" in config["fields"]:
            checks.append(("area-freshness", lambda: check_area_freshness(config, args.skills_root)))
        else:
            skipped.append(
                "area-freshness: skipped. It compares Area options with the folders of a skills root, "
                "so it needs --skills-root and an `area` field in the config"
            )
    if wanted(args.dimension, "suggest") or wanted(args.dimension, "stale"):
        fetch_issue_details(config, items, finished)
    if wanted(args.dimension, "suggest"):
        checks.append(("ready-candidates", lambda: check_ready_candidates(items)))
    if wanted(args.dimension, "stale"):
        checks.append(("stale", lambda: check_stale(items, finished=finished)))

    if wanted(args.dimension, "qa-signoff"):
        checks.append(("qa-signoff", lambda: check_qa_signoff(items, config, finished)))

    for s in skipped:
        print(f"{s}")

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
