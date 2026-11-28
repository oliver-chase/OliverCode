#!/usr/bin/env python3
"""Compares a GitHub Project's field list with the kanban baseline in shared/kanban-baseline.json.
Never edits a board. Each difference prints with its fix. `backlog/SKILL.md` states the baseline.
It runs as `check_board_hygiene.py --verify-baseline`.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

BASELINE_PATH = Path(__file__).resolve().parents[3] / "shared" / "kanban-baseline.json"
SINGLE_SELECT = "ProjectV2SingleSelectField"
NOT_VISIBLE = ("A board's built-in workflows, such as one that moves an item when a pull request merges, "
               "do not appear in the field list, so this check cannot see them. If one sets Status from a pull request, "
               "turn it off on the Project's Workflows page.")


def load_baseline(path=BASELINE_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_fields_from_gh(config):
    result = subprocess.run(
        ["gh", "project", "field-list", str(config["projectNumber"]),
         "--owner", config["projectOwner"], "--format", "json", "--limit", "100"],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh project field-list failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _by_name(fields):
    return {f.get("name", "").lower(): f for f in fields.get("fields", [])}


def _option_names(field):
    return [o.get("name", "") for o in field.get("options", [])]


def _compare_options(label, live, wanted, fix_field):
    problems = []
    live_lower = {n.lower(): n for n in live}
    for name in wanted:
        if name.lower() not in live_lower:
            problems.append(f"{label}: missing option {name}. Fix: add {name} to the {fix_field} field.")
    wanted_lower = {n.lower() for n in wanted}
    for name in live:
        if name.lower() not in wanted_lower:
            problems.append(f"{label}: extra option {name}. Fix: remove {name} from the {fix_field} field "
                            "after moving its items to a baseline option.")
    return problems


def check_baseline(fields, baseline, config=None):
    """Differences between a field list and the baseline, each with its fix."""
    problems = []
    live = _by_name(fields)
    patterns = [re.compile(p, re.IGNORECASE) for p in baseline["forbiddenLanePatterns"]]

    status = live.get("status")
    if status is None or status.get("type") != SINGLE_SELECT:
        problems.append("Status: the board has no single-select Status field. "
                        f"Fix: create a Status field with the lanes {', '.join(baseline['lanes'])}.")
    else:
        lanes = _option_names(status)
        pr_lanes = [n for n in lanes if any(p.search(n) for p in patterns)]
        for name in pr_lanes:
            problems.append(f"Status: lane {name} is driven by pull requests. "
                            f"Fix: move its items to In Progress or QA and delete the lane. {baseline['rule']}")
        rest = [n for n in lanes if n not in pr_lanes]
        problems.extend(_compare_options("Status", rest, baseline["lanes"], "Status"))

    for name, wanted in baseline["fields"].items():
        field = live.get(name.lower())
        if field is None or field.get("type") != SINGLE_SELECT:
            problems.append(f"{name}: the board has no single-select {name} field. Fix: create it.")
            continue
        problems.extend(_compare_options(name, _option_names(field), wanted, name))
    return problems


def run(fields, config=None, baseline_path=BASELINE_PATH, out=print):
    """Print the result and return the number of differences."""
    problems = check_baseline(fields, load_baseline(baseline_path), config)
    if not problems:
        out("kanban baseline: the board matches.")
    else:
        out(f"kanban baseline: {len(problems)} difference(s) from shared/kanban-baseline.json:")
        for p in problems:
            out(f"  - {p}")
    out(NOT_VISIBLE)
    return len(problems)
