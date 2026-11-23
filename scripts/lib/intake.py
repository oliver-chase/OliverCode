"""Intake check on bulk-created issues (#728): open issues without the story template fail the sweep and get one rewrite story.

`check(slug, issues)` runs `check_story_format.check_body` on every open issue. When MIN or more fail, the repo has had a
bulk copy-in: the sweep queues one owner-queue line and files one story, "Rewrite N issues to the story template", whose body
lists the numbers. A repo with an open rewrite story files no second one. Standard library only; the sweep passes in the
`gh` runner so tests need no network.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from lib import agent_loop, candidates, cmd_owner
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))

MIN = 5


def candidate(slug: str, title: str, body: str) -> None:
    """Add the story to the candidates list (#971). No automatic path creates an issue, so reloading a job cannot fill the board."""
    candidates.add("intake", slug, title, body)


SESSION = "intake-check"
TITLE = "Rewrite {n} issues to the story template"
PREFIX = "Rewrite "
MARK = " issues to the story template"
BODY = """**As the owner**, I want the copied-in issues rewritten to the story template, so that I never have to ask for it.

```gherkin
Feature: Have copied-in issues rewritten to the template
  Scenario: Main case
    Given {n} open issues without the story template: {numbers}
    When each is rewritten from skills/backlog/references/story-template.md
    Then check_story_format.py passes on every one
```

Epic: #{epic}
Priority: P2. Size: M. Work type: Story.

Existing coverage checked: `check_story_format.py` already names each missing part, and this story rewrites the issues it names.
"""


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


def epic_of(issues: list[dict], default: int) -> int:
    """The lowest-numbered open issue whose body says `Work type: Epic`, else the default."""
    found = [i["number"] for i in issues if "work type: epic" in (i.get("body") or "").lower()]
    return min(found) if found else default


def check(name: str, slug: str, epic: int = 1, fetch=gh_issues, file=candidate) -> tuple[bool, str]:
    """(failed, line) for one repo. Adds one rewrite candidate when MIN or more open issues lack the template."""
    try:
        issues = fetch(slug)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return True, f"{name}: the intake check did not run ({exc}), so the issue format is unknown"
    bad = failing(issues)
    if len(bad) < MIN:
        return False, f"{name}: intake check clean, {len(bad)} open issue(s) lack the story template"
    open_rewrite = any(i.get("title", "").startswith(PREFIX) and i.get("title", "").endswith(MARK) for i in issues)
    if not open_rewrite:
        file(slug, TITLE.format(n=len(bad)), BODY.format(n=len(bad), numbers=", ".join(f"#{n}" for n in bad), epic=epic_of(issues, epic)))
    return True, f"{name}: {len(bad)} open issue(s) lack the story template" + (", a rewrite story is already open" if open_rewrite else ", one rewrite candidate added")


def run(boards, out=print, **kw) -> int:
    """Check each (name, slug, epic) repo, queue one owner-queue line per repo and return 1 when any fails."""
    failed = 0
    for name, slug, epic in boards:
        bad, line = check(name, slug, epic, **kw)
        out(line)
        cmd_owner.note(SESSION, line)
        failed |= bad
    return int(failed)


PREVENT = "Prevent the repeated block: "
PREVENT_BODY = """**As the owner**, I want the repeated block "{what}" to stop costing a session, so that no one meets it a {nth} time.

```gherkin
Feature: Prevent a repeated block
  Scenario: Main case
    Given the failure log holds {n} entries for the gate {gate}, first seen {first} and last seen {last}
    When a check is added that catches the cause before the gate runs
    Then the block no longer reaches the log
```

Occurrences: {times}
Epic: #{epic}
Priority: P2. Size: S. Work type: Story.

Existing coverage checked: the failure log already counts each occurrence, and no open story covers this one.
"""


def _seen_file():
    from lib import failure_log
    return failure_log.home() / "blocker-seen.json"


def _comment(slug: str, number: int, text: str) -> None:
    subprocess.run(["gh", "api", f"repos/{slug}/issues/{number}/comments", "-f", f"body={text}"], capture_output=True, text=True, timeout=60)


def guard_exists(gate: str) -> bool:
    """False when `gate` names a guard hook (`x_guard`, `x-guard`) that scripts/hooks no longer holds. Any other gate name stands."""
    if not re.fullmatch(r"[\w-]+[_-]guard", gate):
        return True
    want = gate.replace("-", "_")
    return any(p.stem.replace("-", "_") == want for p in (OC_ROOT / "scripts" / "hooks").glob("*.py"))


def prevention(slug: str, epic: int = 1, repeats=None, fetch=gh_issues, file=candidate, comment=_comment) -> list[str]:
    """A blocker the failure log holds 3 or more times adds one prevention candidate, at most `retroFilesPerRun` per run (#971). An open
    story that already names it gets the new occurrences as a comment, a blocker met before adds nothing again, and a refusal from a
    guard the tree no longer has adds nothing. No model call, and no issue is created."""
    from lib import failure_log
    repeats = failure_log.repeated() if repeats is None else repeats
    repeats = {k: v for k, v in repeats.items() if guard_exists(k[0])}
    if not repeats:
        return []
    try:
        issues = fetch(slug)
        seen = json.loads(_seen_file().read_text(encoding="utf-8")) if _seen_file().is_file() else {}
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        return []
    cap = int(candidates.limits()["retroFilesPerRun"])
    lines, filed = [], 0
    for (gate, reason), times in sorted(repeats.items()):
        what = f"{gate}: {reason}"[:100]
        title = PREVENT + what
        key = f"{gate}\t{reason}"
        found = next((i for i in issues if i.get("title", "") == title), None)
        if found:
            if len(times) > seen.get(key, 0):
                comment(slug, found["number"], f"Seen again: {len(times)} entries now, latest {times[-1]}.")
                seen[key] = len(times)
                lines.append(f"{what}: occurrence added to #{found['number']}")
            continue
        if key in seen or filed >= cap:
            continue
        body = PREVENT_BODY.format(what=what, nth=len(times) + 1, n=len(times), gate=gate, first=times[0], last=times[-1],
                                   times=", ".join(times[:10]), epic=epic)
        file(slug, title, body)
        seen[key] = len(times)
        filed += 1
        lines.append(f"{what}: prevention candidate added")
    try:
        _seen_file().write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass
    return lines


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
