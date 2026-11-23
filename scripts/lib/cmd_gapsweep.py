"""Launcher command `gap-sweep`: file one story for each standard a repo has off, every night, with no model call (#725).

`olivercode gap-sweep [--schedule | --unschedule]` reads the feature register (`features.off`, #723) for OliverCode and each
cloned fleet repo that has a board. For each row that is off and that an agent can turn on, it appends one candidate to the local candidates list (#895), at most five per repo per run and the most urgent first,
and files nothing. The owner promotes a candidate with `olivercode candidates promote N`, and groom fills its fields later. A gap with an open story is never added twice: the
sweep comments on that story once a week instead. A gap whose story is closed is never added again, and nothing is added while the repo holds more than the open story cap.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lib import candidates, cmd_owner, failure_log, gh_budget, launchd
from lib.cmd_sweep import boards
from lib.local_config import OC_ROOT

LABEL = "com.olivercode.gap-sweep"
USAGE = "Usage: olivercode gap-sweep [--schedule | --unschedule]"
CAP = 5
REMIND_DAYS = 7
PRIORITY = {"hooks": "P0", "permission-policy": "P0", "board-baseline": "P1", "story-template": "P1"}
BATCH = OC_ROOT / "skills" / "backlog" / "scripts" / "batch_project.py"


def marker(gap_id: str) -> str:
    return f"<!-- gap:{gap_id} -->"


def body(feature, repo: str, epic: int, priority: str) -> str:
    cmd = feature.enable.replace("{repo}", repo)
    return (f"**As the owner**, I want {feature.title.lower()} turned on in {repo}, so that I never have to ask for it.\n\n"
            "```gherkin\n"
            f"Feature: {feature.title} is on\n  Scenario: Main case\n"
            f"    Given {feature.title.lower()} is off in {repo}\n    When `{feature.enable.replace('{repo}', repo)}` runs\n"
            f"    Then `olivercode features --repo {repo}` shows {feature.title.lower()} on\n```\n\n"
            f"Epic: #{epic}\nPriority: {priority}. Size: XS. Work type: Story.\n\n"
            "Existing coverage checked: the feature register lists this feature as off, and no open story enables it.\n\n"
            f"Filed by the nightly gap sweep from the feature register. Enable command: `{cmd}`.\n{marker(feature.id)}\n")


def gh(args: list[str]):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    return done.stdout if done.returncode == 0 else None


def gap_stories(slug: str, run=gh) -> tuple[dict[str, int], set[str], int] | None:
    """(open gap stories by feature id, feature ids whose story is closed, open story count), or None when the list could not be read."""
    raw = run(["api", f"repos/{slug}/issues?state=all&per_page=100", "--paginate", "--jq",
               '.[] | select(has("pull_request") | not) | {number, state, body}'])
    if raw is None:
        return None
    found, closed, open_count = {}, set(), 0
    for line in raw.splitlines():
        if line.strip():
            issue = json.loads(line)
            is_closed = issue.get("state") == "closed"
            open_count += 0 if is_closed else 1
            for gap in re.findall(r"<!-- gap:([\w-]+) -->", issue.get("body") or ""):
                if is_closed:
                    closed.add(gap)
                else:
                    found[gap] = issue["number"]
    return found, closed - set(found), open_count


def epic_of(config: Path) -> int | None:
    """The open epic the stories hang under: the one about gaps, else the first open epic on the board."""
    import board_grooming
    import check_board_hygiene
    cfg = json.loads(config.read_text(encoding="utf-8"))
    epics = [i for i in check_board_hygiene.load_items(cfg) if str(board_grooming.field(i, "work type") or "").lower() == "epic"
             and i.get("status") != "Complete"]
    pick = next((i for i in epics if re.search(r"gap|self-filling", (i["content"].get("title") or ""), re.I)), epics[0] if epics else None)
    return pick["content"]["number"] if pick else None


def create(slug: str, title: str, text: str, run=gh) -> int | None:
    """Append the story to the candidates list. Nothing reaches the board until the owner promotes it, so there is no issue number."""
    candidates.add("gap-sweep", slug, title, text)
    return None


def set_fields(config: Path, number: int, priority: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"issues": [{"number": number, "fields": {"status": "Ready", "priority": priority, "size": "XS", "workType": "Story"}}]}, f)
    sys.path.insert(0, str(BATCH.parent))
    import batch_project
    batch_project.main(["--config", str(config), "--input", f.name])


def sweep_repo(name: str, config: Path, gaps: list, slug: str, epic: int | None, state: dict, now: float, run=gh,
               make=create, fields=set_fields, comment=None) -> tuple[int, int]:
    """(filed, commented) for one repo. `state` keeps the time of each reminder so a rerun posts nothing."""
    comment = comment or (lambda n, t: run(["api", "-X", "POST", f"repos/{slug}/issues/{n}/comments", "-f", f"body={t}"]))
    read = gap_stories(slug, run)
    if read is None or epic is None:
        cmd_owner.note("gap-sweep", f"{name}: the gap sweep did not run ({'the issue list could not be read' if read is None else 'no open epic to file under'})")
        return 0, 0
    existing, closed, open_count = read
    room = open_count <= candidates.limits()["openStoryCap"]
    filed = commented = 0
    for feature in sorted(gaps, key=lambda g: (PRIORITY.get(g.id, "P2"), g.id)):
        title = f"Turn on {feature.title.lower()} in {name}"
        if feature.id in existing:
            number, key = existing[feature.id], f"{slug}#{existing[feature.id]}"
            if now - state.get(key, 0) > REMIND_DAYS * 86400:
                comment(number, f"The nightly gap sweep still finds {feature.title.lower()} off in {name}. Enable command: `{feature.enable.replace('{repo}', name)}`.")
                state[key], commented = now, commented + 1
        elif feature.id not in closed and room and not candidates.has(slug, title) and filed < CAP:
            priority = PRIORITY.get(feature.id, "P2")
            number = make(slug, title, body(feature, name, epic, priority))
            if number:
                fields(config, number, priority)
            if number or candidates.has(slug, title):
                filed += 1
    return filed, commented


def run(board_list=boards, now: float | None = None) -> int:
    try:
        from lib import features
    except ImportError:
        print("The feature register (`olivercode features`, #723) is not installed here, so the gap sweep did not run.")
        return 1
    now = time.time() if now is None else now
    path = failure_log.home() / "gap-sweep-state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    held = gh_budget.refusal() or gh_budget.points_refusal()
    bad = 0
    for name, config in board_list():
        if held:
            cmd_owner.note("gap-sweep", f"{name}: the gap sweep did not run ({held.split('. ')[0]})")
            bad += 1
            continue
        try:
            cfg = json.loads(config.read_text(encoding="utf-8"))
            root = config.resolve().parent.parent
            gaps = features.off(root)
            filed, commented = sweep_repo(name, config, gaps, f"{cfg['repoOwner']}/{cfg['repoName']}", epic_of(config) if gaps else 0, state, now)
        except (Exception, SystemExit) as exc:
            cmd_owner.note("gap-sweep", f"{name}: the gap sweep failed: {str(exc)[:200]}")
            bad += 1
            continue
        print(f"{name}: {len(gaps)} gap(s), {filed} candidate(s) added, {commented} reminder(s)")
        if filed:
            cmd_owner.note("gap-sweep", f"{name}: added {filed} candidate(s) for standards that were off. Run `olivercode candidates`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return 1 if bad else 0


def schedule(on: bool) -> int:
    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["gap-sweep"], "gap-sweep.out", StartCalendarInterval={"Hour": 3, "Minute": 30}),
                            "gap sweep job", "`olivercode gap-sweep` runs daily at 03:30. Remove it with `olivercode gap-sweep --unschedule`.")


def command_gapsweep(argv: list[str]) -> int:
    return launchd.command_with_schedule(argv, USAGE, schedule, run)
