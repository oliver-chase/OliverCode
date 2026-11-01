#!/usr/bin/env python3
"""Checks the live GitHub Project board for hygiene findings. Never auto-fixes. Needs `gh` on PATH.
`board-hygiene/SKILL.md` states what each dimension checks.

Usage:
    check_board_hygiene.py --config path/to/backlog-config.json                       # every dimension but area
    check_board_hygiene.py --config CFG --skills-root DIR                             # adds area-freshness against DIR's folders
    check_board_hygiene.py --config CFG --dimension X    # one of: fields, drift, duplicates, ready, area, suggest
The config is the `docs/backlog-config.json` of the repo whose board you check.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Area options that outlive the folder they named: frozen labels on Complete items.
RETIRED_AREA_OPTIONS = {"document-skills", "deliverable-builder"}
# A family with no folder in this repo whose open items keep the label.
PARKED_AREA_OPTIONS = {"growth"}
# Not a folder: the catch-all value for cross-family work.
VIRTUAL_AREA_OPTIONS = {"fleet-wide"}

REQUIRED_STATUSES = {"Backlog", "Ready", "In Progress"}
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
        "--owner", config["projectOwner"], "--format", "json", "--limit", "2000",
    ])
    return json.loads(out)["items"]


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
            "issue", "list", "--repo", repo, "--state", "all", "--limit", "2000",
            "--json", "number,state,title",
        ]))
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
    ready = [i for i in items if i.get("status") == "Ready"]
    if not ready:
        return ["Ready column is empty -- nothing queued as next-up work"]
    return []


def discover_families(root):
    # A family is any folder directly under the fleet root. Skills sit inside it, so no deeper walk is needed.
    return {
        d.name for d in Path(root).iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "docs"
    }


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
    known_good = live_families | RETIRED_AREA_OPTIONS | PARKED_AREA_OPTIONS | VIRTUAL_AREA_OPTIONS
    problems = []
    for opt in sorted(live_options - known_good):
        problems.append(
            f"Area option '{opt}' matches no live family folder, no retired label, "
            f"no virtual catch-all -- possibly stale"
        )
    for fam in sorted(live_families - live_options):
        problems.append(f"Live family folder '{fam}' has no matching Area option")
    return problems


def check_ready_candidates(items):
    """Fires only when Ready is empty. Needs bodies fetched onto `items` first. Whitespace is
    collapsed before matching, so a phrase that spans a wrapped line still matches."""
    if any(i.get("status") == "Ready" for i in items):
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


def fetch_bodies(config, items, finished="Complete"):
    """item-list's own JSON has no body field -- one gh issue list call fills every open
    item's body in a single pass, not one call per issue."""
    open_items = [i for i in items if i.get("status") != finished]
    if not open_items:
        return
    out = run_gh([
        "issue", "list", "--repo", f"{config['repoOwner']}/{config['repoName']}",
        "--state", "open", "--limit", "500", "--json", "number,body",
    ])
    bodies = {row["number"]: row["body"] for row in json.loads(out)}
    for i in open_items:
        c = i.get("content", {})
        num = c.get("number")
        if num in bodies:
            c["body"] = bodies[num]


def load_config(path):
    """The repo's backlog config. A missing path exits with one line that says where the file lives."""
    if path is None or not Path(path).is_file():
        sys.exit(f"backlog config not found ({path}). Pass --config with the path to docs/backlog-config.json "
                 "of the repo whose board you check.")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", choices=["fields", "drift", "duplicates", "ready", "area", "suggest"])
    parser.add_argument("--config", type=Path, help="path to the repo's docs/backlog-config.json (required)")
    parser.add_argument(
        "--skills-root", type=Path,
        help="folder whose direct sub-folders are the Area options' families; area-freshness runs only with it",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    items = load_items(config)
    finished, open_statuses = resolve_statuses(config, live_status_names(config))

    checks = []
    skipped = []
    if args.dimension in (None, "fields"):
        checks.append(("required-fields", lambda: check_required_fields(items, config, open_statuses)))
    if args.dimension in (None, "drift"):
        checks.append(("status-drift", lambda: check_status_drift(items, config, finished)))
    if args.dimension in (None, "duplicates"):
        checks.append(("duplicate-cards", lambda: check_duplicate_cards(items)))
    if args.dimension in (None, "ready"):
        checks.append(("ready-occupancy", lambda: check_ready_occupancy(items)))
    if args.dimension in (None, "area"):
        if args.skills_root and "area" in config["fields"]:
            checks.append(("area-freshness", lambda: check_area_freshness(config, args.skills_root)))
        else:
            skipped.append(
                "area-freshness: skipped. It compares Area options with the folders of a skills root, "
                "so it needs --skills-root and an `area` field in the config"
            )
    if args.dimension in (None, "suggest"):
        fetch_bodies(config, items, finished)
    if args.dimension in (None, "suggest"):
        checks.append(("ready-candidates", lambda: check_ready_candidates(items)))

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
