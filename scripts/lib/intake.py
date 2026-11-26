"""Intake check on bulk-created issues (#728) and the repeated-blocker report. Both only report; neither files a story or edits an issue (#1275).

`check(slug, issues)` runs `check_story_format.check_body` on every open issue. When MIN or more fail, the repo has had a
bulk copy-in, and the check names how many lack the template. `repeated_blockers` names each gate failure the failure log holds
three or more times. Standard library only; the sweep passes in the `gh` runner so tests need no network.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from lib import agent_loop, cmd_owner
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))

MIN = 5


SESSION = "intake-check"
PREFIX = "Rewrite "  # a story an earlier release filed for the rewrite is not itself counted as malformed
MARK = " issues to the story template"
def gh_issues(slug: str) -> list[dict]:
    done = subprocess.run(["gh", "issue", "list", "--repo", slug, "--state", "open", "--limit", "500",
                           "--json", "number,title,body,labels"], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[:120] or "gh issue list failed")
    return json.loads(done.stdout or "[]")


def failing(issues: list[dict]) -> list[int]:
    import check_story_format
    out = []
    for i in issues:
        title = i.get("title", "")
        if title.startswith(PREFIX) and title.endswith(MARK):
            continue
        labels = {(l.get("name") if isinstance(l, dict) else l) for l in i.get("labels") or []}
        if "epic" in {x.lower() for x in labels if x}:
            continue
        if check_story_format.check_body(i.get("body") or "", coverage=False):
            out.append(i["number"])
    return sorted(out)


def check(name: str, slug: str, fetch=gh_issues) -> tuple[bool, str]:
    """(failed, line) for one repo. Fails when MIN or more open issues lack the template, and files nothing."""
    try:
        issues = fetch(slug)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return True, f"{name}: the intake check did not run ({exc}), so the issue format is unknown"
    bad = failing(issues)
    if len(bad) < MIN:
        return False, f"{name}: intake check clean, {len(bad)} open issue(s) lack the story template"
    return True, f"{name}: {len(bad)} open issue(s) lack the story template: " + ", ".join(f"#{n}" for n in bad[:20])


def run(boards, out=print, **kw) -> int:
    """Check each (name, slug, epic) repo, queue one owner-queue line per repo and return 1 when any fails."""
    failed = 0
    for name, slug, _epic in boards:
        bad, line = check(name, slug, **kw)
        out(line)
        cmd_owner.note(SESSION, line)
        failed |= bad
    return int(failed)


def guard_exists(gate: str) -> bool:
    """False when `gate` names a guard hook (`x_guard`, `x-guard`) that scripts/hooks no longer holds. Any other gate name stands."""
    if not re.fullmatch(r"[\w-]+[_-]guard", gate):
        return True
    want = gate.replace("-", "_")
    return any(p.stem.replace("-", "_") == want for p in (OC_ROOT / "scripts" / "hooks").glob("*.py"))


def repeated_blockers(repeats=None) -> list[str]:
    """One report line for each blocker the failure log holds 3 or more times, from a guard the tree still has. It files and edits nothing (#1275)."""
    from lib import failure_log
    repeats = failure_log.repeated() if repeats is None else repeats
    return [f"{gate}: {reason}"[:100] + f" blocked {len(times)} times, latest {times[-1]}"
            for (gate, reason), times in sorted(repeats.items()) if guard_exists(gate)]


# Split open stories by files area so non-overlapping stories go to builders in parallel (#794).
AREA = re.compile(r"^\W*Files area:\W*(.+)$", re.I | re.M)
CREATES = re.compile(r"^\W*Creates:\W*(.+)$", re.I | re.M)
WAIT_LINE = re.compile(r"\b(?:wait\w*|until|after|once|data|window)\b", re.I)
WAIT_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
WAIT_SPAN = re.compile(r"\b(\d+)[- ]days?\s+(?:of\s+)?(?:data|window|wait)|\bwait\w*\s+(?:for\s+)?(\d+)\s+days?\b", re.I)
WAIT_DAYS = 14
SMALL = ("XS", "S")


def _listed(line: re.Pattern, body: str) -> list[str]:
    m = line.search(body or "")
    return [t.strip("`.,;*()") for t in re.split(r"[,;\s]+", m.group(1)) if t.strip("`.,;*()")] if m else []


def files_area(body: str) -> list[str]:
    """The paths on the story's `Files area:` line, or [] when it has none."""
    return _listed(AREA, body)


def folders(area: list[str], root) -> list[str]:
    """The Files area entries that name a folder: a path ending in "/" or a folder under root. One overlaps every story inside it (#1077)."""
    return [p for p in area if p.endswith("/") or (root is not None and (Path(root) / p).is_dir())]


def creates(body: str) -> list[str]:
    """The paths on the story's `Creates:` line, the new files it adds (#1004), or [] when it has none."""
    return _listed(CREATES, body)


def overlaps(a: list[str], b: list[str]) -> bool:
    """True when the two areas share a file, or one names a folder that holds the other's file."""
    return any(x == y or x.rstrip("/") + "/" == y[:len(x.rstrip("/")) + 1] or y.rstrip("/") + "/" == x[:len(y.rstrip("/")) + 1] for x in a for y in b)


def in_area(path: str, area: list[str]) -> bool:
    """True when the path is inside the area or is any test file (test_*.py). The rules ask for a test with every change, and a module's test
    often has another name (cmd_status.py is tested in test_status.py) or covers a neighbour, so refusing it threw away finished builds.
    The landing's weakened-test check still guards every test file (#1073, #1078)."""
    name = Path(path).name
    return overlaps([path], area) or (name.startswith("test_") and name.endswith(".py"))


def long_wait(body: str, today: datetime.date | None = None) -> str:
    """The wait a story parks its work on beyond WAIT_DAYS days, or ''."""
    today = today or datetime.date.today()
    for line in (body or "").splitlines():
        if not WAIT_LINE.search(line):
            continue
        for d in WAIT_DATE.findall(line):
            try:
                if (datetime.date.fromisoformat(d) - today).days > WAIT_DAYS:
                    return d
            except ValueError:
                pass
        for m in WAIT_SPAN.finditer(line):
            n = int(m.group(1) or m.group(2))
            if n > WAIT_DAYS:
                return f"{n} days"
    return ""


def models(story: dict, session: str = "") -> tuple[str, str, str]:
    """(builder model, reader model, the rule that chose the builder) a story starts on (#1015, #1026): the builder is the one agent_loop starts with,
    after a restart escalation, and the reader is never weaker than Sonnet. The brief and the status line name all three, so they say what the runner does."""
    from lib import cmd_groom  # cmd_groom imports intake, so the import waits until a story is routed
    base, why = agent_loop.route(cmd_groom.size_of(story), story.get("labels") or (), files_area(story.get("body") or ""), cmd_groom.priority_of(story))
    builder = agent_loop.restart_model(session, base)
    if builder != base:
        why += "; a restart escalated it one level"
    return builder, agent_loop.reader_for(builder), why


def plan(issues: list[dict], today: datetime.date | None = None) -> dict:
    """{"groups": [[numbers in order]], "rewrite": [numbers with no files area], "waits": {number: flag}, "models": {number: (builder, QA)}}.
    Stories that share a file sit in one group in priority order, and different groups run in parallel."""
    from lib import cmd_groom
    todo = [i for i in issues if "work type: epic" not in (i.get("body") or "").lower() and "epic" not in {
        (l.get("name") if isinstance(l, dict) else l or "").lower() for l in i.get("labels") or []}]
    areas = {i["number"]: files_area(i.get("body") or "") for i in todo}
    rank = {i["number"]: (cmd_groom.priority_of(i), i["number"]) for i in todo}
    groups: list[list[int]] = []
    for n in sorted((n for n in areas if areas[n]), key=rank.get):
        hit = [g for g in groups if any(overlaps(areas[n], areas[m]) for m in g)]
        merged = sorted({m for g in hit for m in g} | {n}, key=rank.get)
        groups = [g for g in groups if g not in hit] + [merged]
    waits = {}
    for i in todo:
        if when := long_wait(i.get("body") or "", today):
            waits[i["number"]] = (f"waits on {when}: rewrite it to " + ("do it now" if rank[i["number"]][0] in ("P0", "P1") else "close it")
                                  + " (do it now or close it)")
    return {"groups": sorted(groups, key=lambda g: rank[g[0]]), "rewrite": sorted(n for n in areas if not areas[n]), "waits": waits,
            "models": {i["number"]: models(i, f"story-{i['number']}") for i in todo if areas[i["number"]]}}


def render(found: dict) -> str:
    lines = [f"Parallel group {k}: " + " then ".join(f"#{n} ({found['models'][n][0]} builder, {found['models'][n][1]} QA, chosen for {found['models'][n][2]})" for n in g)
             for k, g in enumerate(found["groups"], 1)]
    lines += [f"#{n} names no files area: rewrite it, it is not dispatched" for n in found["rewrite"]]
    lines += [f"#{n} {why}" for n, why in sorted(found["waits"].items())]
    return "\n".join(lines) or "No open stories to split."
