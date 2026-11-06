#!/usr/bin/env python3
"""Checks the live GitHub Project board for hygiene findings. Never auto-fixes. Needs `gh` on PATH.
`backlog/SKILL.md` states what each dimension checks.

Usage:
    check_board_hygiene.py --config path/to/backlog-config.json                       # every dimension
    check_board_hygiene.py --config CFG --dimension X [--dimension Y]  # only these: fields, drift, duplicates, qa-signoff, groom
    check_board_hygiene.py --config CFG --verify-config  # stop after the fork and placeholder checks, touching nothing
    check_board_hygiene.py --config CFG --verify-baseline [--fields-file F]  # compare the board's fields with shared/kanban-baseline.json
The config is the `docs/backlog-config.json` of the repo whose board you check. This script only reads.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import check_kanban_baseline as kanban
import check_qa_signoff as qa

ITEM_LIMIT = 2000

# Every baseline lane except the finished one holds open work (shared/kanban-baseline.json).
REQUIRED_STATUSES = {lane for lane in kanban.load_baseline()["lanes"] if lane.lower() not in {"complete", "done"}}
# The finished column's config key. Every other column, such as Todo or In review, holds open work.
FINISHED_STATUS_KEYS = {"complete", "done"}


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


# Grooming finds work the board has not caught up with. Every finding is a judgment for the owner.
WAITING_STATUSES = {"Backlog", "Ready"}
STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into", "every", "each", "when",
             "make", "makes", "only", "its", "their", "them", "they", "one", "all", "add", "fix", "put", "move",
             "bring"}


def title_words(title):
    words = re.findall(r"[a-z0-9][a-z0-9-]*", title.lower())
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words if len(w) > 2 and w not in STOPWORDS}


def overlapping_titles(items, open_statuses, min_shared=3, ratio=0.6):
    """Pairs of open stories whose titles share most of the shorter title's content words. An epic
    shares words with its own stories by design, so epics are left out."""
    open_items = [(i["content"]["number"], title_words(i["content"].get("title", "")))
                  for i in items if i.get("status") in open_statuses and i.get("content", {}).get("number")
                  and i.get("work Type") != "Epic"]
    problems = []
    for a in range(len(open_items)):
        for b in range(a + 1, len(open_items)):
            (na, wa), (nb, wb) = open_items[a], open_items[b]
            shared = wa & wb
            if len(shared) >= min_shared and len(shared) / min(len(wa), len(wb)) >= ratio:
                problems.append(f"#{na} and #{nb} share {', '.join(sorted(shared))}: "
                                "possible duplicate or superseded pair, close one or link them")
    return problems


def built_not_moved(items, comments_by_number):
    """Open items still in Backlog or Ready whose issue carries a log_action builder entry."""
    problems = []
    for i in items:
        number = i.get("content", {}).get("number")
        if i.get("status") not in WAITING_STATUSES or number not in comments_by_number:
            continue
        if any("- Role: builder" in (c.get("body") or "") for c in comments_by_number[number]):
            problems.append(f"#{number} \"{i['content'].get('title', '')[:50]}\" ({i.get('status')}): "
                            "has a builder entry, move it to QA")
    return problems


def epic_rollup(items, summaries, finished):
    """Open epics whose Status lags their sub-issues. `summaries` maps number to (total, completed)."""
    problems = []
    for i in items:
        number = i.get("content", {}).get("number")
        if i.get("work Type") != "Epic" or i.get("status") == finished or number not in summaries:
            continue
        total, completed = summaries[number]
        title = i["content"].get("title", "")[:50]
        if total and completed == total:
            problems.append(f"#{number} \"{title}\": all {total} sub-issues closed, move the epic to {finished}")
        elif completed and i.get("status") in WAITING_STATUSES:
            problems.append(f"#{number} \"{title}\" ({i.get('status')}): {completed} of {total} "
                            "sub-issues closed, move the epic to In Progress")
    return problems


def open_issue_comments(config):
    repo = f"{config['repoOwner']}/{config['repoName']}"
    issues = json.loads(run_gh(["issue", "list", "--repo", repo, "--state", "open",
                                "--limit", str(ITEM_LIMIT), "--json", "number,comments"]))
    return {x["number"]: x["comments"] for x in issues}


def epic_summaries(items, config, finished):
    out = {}
    for i in items:
        number = i.get("content", {}).get("number")
        if i.get("work Type") != "Epic" or i.get("status") == finished or not number:
            continue
        data = json.loads(run_gh(["api", "graphql", "-f",
            f'query={{ repository(owner: "{config["repoOwner"]}", name: "{config["repoName"]}") '
            f'{{ issue(number: {number}) {{ subIssuesSummary {{ total completed }} }} }} }}']))
        summary = data["data"]["repository"]["issue"]["subIssuesSummary"]
        out[number] = (summary["total"], summary["completed"])
    return out


def check_grooming(items, config, finished, open_statuses):
    return (built_not_moved(items, open_issue_comments(config))
            + epic_rollup(items, epic_summaries(items, config, finished), finished)
            + overlapping_titles(items, open_statuses))


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


DIMENSIONS = ["fields", "drift", "duplicates", "qa-signoff", "groom"]


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
    if wanted(args.dimension, "fields"):
        checks.append(("required-fields", lambda: check_required_fields(items, config, open_statuses)))
    if wanted(args.dimension, "drift"):
        checks.append(("status-drift", lambda: check_status_drift(items, config, finished)))
    if wanted(args.dimension, "duplicates"):
        checks.append(("duplicate-cards", lambda: check_duplicate_cards(items)))
    if wanted(args.dimension, "qa-signoff"):
        checks.append(("qa-signoff", lambda: check_qa_signoff(items, config, finished)))
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
