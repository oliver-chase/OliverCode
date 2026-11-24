#!/usr/bin/env python3
"""Queue Project field changes and send them as aliased GraphQL mutations.

The input is JSON: {"issues": [{"number": 42, "fields": {"status": "Ready"}}]}.
A Status change that would move a closed issue off the finished column is skipped and printed, so a replayed
queue never reopens closed work. `--reopen N`, or "reopen": true on the issue, applies it and reopens the issue.
Several callers append to ~/.olivercode/gh-project-queue.json under one lock; the caller that
can run drains compatible work in one add mutation and update chunks of fifteen.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import board_mirror  # noqa: E402
import gh_budget  # noqa: E402
from check_kanban_baseline import scope_hint  # noqa: E402

CHUNK = 15


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def normalize(data, cfg):
    """Validate a portable, human-readable request before it reaches the shared queue."""
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list) or not data["issues"]:
        raise ValueError("input must contain a non-empty issues list")
    fields = cfg.get("fields", {})
    result = []
    for issue in data["issues"]:
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int) or issue["number"] < 1:
            raise ValueError("each issue needs a positive integer number")
        requested = issue.get("fields")
        if not isinstance(requested, dict) or not requested:
            raise ValueError(f"#{issue['number']} needs at least one field")
        values = {}
        for field, value in requested.items():
            options = fields.get(field, {}).get("options", {})
            if value not in options:
                raise ValueError(f"#{issue['number']}: {field}={value!r} is not in the config")
            values[field] = value
        normalized = {"number": issue["number"], "fields": values}
        if "reopen" in issue:
            normalized["reopen"] = bool(issue["reopen"])
        result.append(normalized)
    return result


def with_queue(fn):
    home = gh_budget.home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "gh-project-queue.json"
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            try:
                queue = json.load(fh) or []
            except ValueError:
                queue = []
            result, queue = fn(queue)
            fh.seek(0)
            fh.truncate()
            json.dump(queue, fh, sort_keys=True)
            fh.write("\n")
            return result
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def request(runner, query, write=True):
    """Run one mutation, retrying one transient gateway failure without multiplying writes."""
    why = gh_budget.refusal() or (gh_budget.reserve_write() if write else "")
    if why:
        raise RuntimeError(why)
    last = ""
    for _ in range(2):
        done = runner(["api", "graphql", "-f", f"query={query}"])
        last = (done.stderr or done.stdout or "gh api failed").strip()
        if done.returncode == 0:
            return json.loads(done.stdout)
        if "502" not in last:
            break
    if gh_budget.is_limit(last):
        gh_budget.note_limit(who="batch_project")
    raise RuntimeError(last + scope_hint(last))


def discovery(cfg, issues, runner, states=None):
    """Each issue's card ID on the project, or None. STATES, when given, is filled with each issue's OPEN or CLOSED."""
    aliases = " ".join(f"i{n}:issue(number:{issue['number']}){{state projectItems(first:50){{nodes{{id project{{id}}}}}}}}"
                       for n, issue in enumerate(issues))
    query = f"query{{repository(owner:\"{cfg['repoOwner']}\",name:\"{cfg['repoName']}\"){{{aliases}}}}}"
    data = request(runner, query, write=False)["data"]["repository"]
    found = {}
    for n, issue in enumerate(issues):
        nodes = data[f"i{n}"]["projectItems"]["nodes"]
        found[issue["number"]] = next((node["id"] for node in nodes if node["project"]["id"] == cfg["projectId"]), None)
        if states is not None:
            states[issue["number"]] = data[f"i{n}"].get("state")
    return found


def mutation_add(project, numbers):
    bits = " ".join(f"a{n}:addProjectV2ItemById(input:{{projectId:\"{project}\",contentId:\"{content}\"}})"
                    f"{{item{{id}}}}" for n, content in numbers)
    return f"mutation{{{bits}}}"


def mutation_updates(cfg, updates):
    bits = []
    for n, (item, field, value) in enumerate(updates):
        bits.append(f"u{n}:updateProjectV2ItemFieldValue(input:{{projectId:\"{cfg['projectId']}\",itemId:\"{item}\","
                    f"fieldId:\"{cfg['fields'][field]['id']}\",value:{{singleSelectOptionId:\"{cfg['fields'][field]['options'][value]}\"}}}})"
                    "{projectV2Item{id}}")
    return f"mutation{{{' '.join(bits)}}}"


# GitHub's answer when a number is no issue in the repo, which no retry changes.
PERMANENT = re.compile(r"Could not resolve to an? (Issue|PullRequest)|NOT_FOUND")


FINISHED = {"complete", "done"}


def closed_guard(issues, states):
    """(issues to apply, skipped changes, numbers to reopen). A Status change that moves a closed issue off the
    finished column is dropped unless the issue asks to reopen; its other fields still apply."""
    kept, skipped, reopen = [], [], []
    for issue in issues:
        status = issue["fields"].get("status")
        if states.get(issue["number"]) != "CLOSED" or not status or status.lower() in FINISHED:
            kept.append(issue)
        elif issue.get("reopen"):
            kept.append(issue)
            reopen.append(issue["number"])
        else:
            skipped.append((issue["number"], f"status={status}"))
            rest = {k: v for k, v in issue["fields"].items() if k != "status"}
            if rest:
                kept.append({**issue, "fields": rest})
    return kept, skipped, reopen


def reopen_issue(cfg, number, runner):
    why = gh_budget.refusal() or gh_budget.reserve_write()
    if why:
        raise RuntimeError(why)
    done = runner(["api", "-X", "PATCH", f"repos/{cfg['repoOwner']}/{cfg['repoName']}/issues/{number}", "-f", "state=open"])
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "gh api failed").strip())


def drain(cfg, issues, runner):
    """Apply ISSUES' field changes. Returns (issues applied, field updates sent, skipped (number, change) pairs)."""
    states = {}
    item_ids = discovery(cfg, issues, runner, states)
    allowed_issues, skipped, reopen = closed_guard(issues, states)
    if not allowed_issues:
        return 0, 0, skipped
    missing = [issue for issue in allowed_issues if not item_ids[issue["number"]]]
    if missing:
        # A new issue's node ID is exposed by the discovery query only indirectly. Query aliases again for IDs.
        aliases = " ".join(f"i{n}:issue(number:{issue['number']}){{id}}" for n, issue in enumerate(missing))
        query = f"query{{repository(owner:\"{cfg['repoOwner']}\",name:\"{cfg['repoName']}\"){{{aliases}}}}}"
        data = request(runner, query, write=False)["data"]["repository"]
        content = [(n, data[f"i{n}"]["id"]) for n, issue in enumerate(missing)]
        added = request(runner, mutation_add(cfg["projectId"], content))["data"]
        for n, issue in enumerate(missing):
            item_ids[issue["number"]] = added[f"a{n}"]["item"]["id"]
    updates = [(item_ids[issue["number"]], field, value) for issue in allowed_issues
               for field, value in issue["fields"].items()]
    for start in range(0, len(updates), CHUNK):
        request(runner, mutation_updates(cfg, updates[start:start + CHUNK]))
    for number in reopen:
        reopen_issue(cfg, number, runner)
    return len(allowed_issues), len(updates), skipped


def run_gh(args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def merge_issues(issues):
    """One card per issue even when separate agents queued complementary fields."""
    merged = {}
    for issue in issues:
        card = merged.setdefault(issue["number"], {"number": issue["number"], "fields": {}})
        card["fields"].update(issue["fields"])
        if issue.get("reopen"):
            card["reopen"] = True
    return list(merged.values())


def main(argv=None, runner=run_gh, out=sys.stdout, err=sys.stderr):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True, help="JSON file, or - for stdin, containing issue numbers and named fields")
    parser.add_argument("--reopen", type=int, action="append", default=[], metavar="N",
                        help="apply the Status change to closed issue N and reopen it")
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        data = json.load(sys.stdin) if args.input == "-" else load(args.input)
        issues = normalize(data, cfg)
        unknown = sorted(set(args.reopen) - {issue["number"] for issue in issues})
        if unknown:
            raise ValueError(f"--reopen names #{unknown[0]}, which the input does not hold")
        for issue in issues:
            if issue["number"] in args.reopen:
                issue["reopen"] = True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"batch_project: invalid input: {exc}", file=err)
        return 2
    job = {"cfg": cfg, "issues": issues}
    with_queue(lambda queue: (None, queue + [job]))
    hold = gh_budget.refusal()
    if hold:
        print(f"batch_project: queued {len(issues)} issue(s); {hold}", file=out)
        return 0
    def take(queue):
        matching = [item for item in queue if item["cfg"]["projectId"] == cfg["projectId"]]
        other = [item for item in queue if item not in matching]
        merged = merge_issues([issue for item in matching for issue in item["issues"]])
        try:
            result = drain(cfg, merged, runner)
        except (RuntimeError, KeyError, TypeError) as exc:
            # A rate limit or hold keeps the work for a later run.
            if isinstance(exc, RuntimeError) and (gh_budget.is_limit(str(exc)) or gh_budget.refusal()):
                return (exc, queue)
            # Apply each issue alone. Only a failure that would repeat on every run, a number that is no issue or a
            # field the config no longer has, leaves the queue; any other error keeps the issue for the next run.
            count = updates = 0
            dropped, kept, skipped_all = [], [], []
            for i, issue in enumerate(merged):
                try:
                    c, u, s = drain(cfg, [issue], runner)
                except (KeyError, TypeError) as one:
                    dropped.append(f"#{issue['number']}: the config has no {one}")
                    continue
                except RuntimeError as one:
                    if gh_budget.is_limit(str(one)) or gh_budget.refusal():
                        return (one, other + [{"cfg": cfg, "issues": kept + merged[i:]}])
                    if PERMANENT.search(str(one)):
                        dropped.append(f"#{issue['number']}: {one}")
                    else:
                        kept.append(issue)
                        print(f"batch_project: kept #{issue['number']} queued after: {one}", file=err)
                    continue
                count, updates = count + c, updates + u
                skipped_all.extend(s)
            return ((count, updates, dropped, skipped_all), other + ([{"cfg": cfg, "issues": kept}] if kept else []))
        c, u, s = result
        return ((c, u, [], s), other)
    result = with_queue(take)
    if isinstance(result, RuntimeError):
        print(f"batch_project: {result}; rate-limited work stays queued", file=err)
        return 1
    count, updates, dropped, skipped = result
    board_mirror.invalidate()  # the board changed, so the shared item list is stale
    print(f"batch_project: applied {updates} field update(s) across {count} queued issue(s)", file=out)
    for num, change in skipped:
        print(f"batch_project: skipped {change} on closed #{num}, so it stays closed and Complete. "
              f"Pass --reopen {num} to reopen it.", file=out)
    for line in dropped:
        print(f"batch_project: dropped {line}; it cannot succeed, so it left the queue", file=err)
    return 1 if dropped else 0


if __name__ == "__main__":
    raise SystemExit(main())
