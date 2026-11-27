"""What drain, dispatch and filing read from a story: its Size and Priority, its Files area, the filing fit check (#1004) and the
repeated-blocker report. Nothing here files a story or edits an issue (#1275). Standard library only."""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from lib import agent_loop
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))

SECURITY = re.compile(r"secret|credential|leak|vulnerab|security|data loss|lose data|lost data", re.I)
DEFECT = re.compile(r"\b(bug|broken|fails?|failing|crash|regress\w*|wrong)\b", re.I)
SIZES = ((500, "XS"), (1000, "S"), (2000, "M"), (4000, "L"))


def gh_issues(slug: str) -> list[dict]:
    done = subprocess.run(["gh", "issue", "list", "--repo", slug, "--state", "open", "--limit", "500",
                           "--json", "number,title,body,labels"], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[:120] or "gh issue list failed")
    return json.loads(done.stdout or "[]")


def priority_of(story):
    """The Priority line the story states, else P0 for security and data loss, P1 for a defect, P2 for the rest."""
    text = f"{story.get('title') or ''}\n{story.get('body') or ''}"
    if m := re.search(r"Priority:\s*(P[012])\b", story.get("body") or ""):
        return m.group(1)
    return "P0" if SECURITY.search(text) else "P1" if DEFECT.search(text) else "P2"


def size_of(story):
    """The Size line the story states, else one by the length of its body."""
    body = story.get("body") or ""
    if m := re.search(r"Size:\s*(XS|S|M|L|XL)\b", body):
        return m.group(1)
    return next((name for limit, name in SIZES if len(body) < limit), "XL")


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
    base, why = agent_loop.route(size_of(story), story.get("labels") or (), files_area(story.get("body") or ""), priority_of(story))
    builder = agent_loop.restart_model(session, base)
    if builder != base:
        why += "; a restart escalated it one level"
    return builder, agent_loop.reader_for(builder), why


def plan(issues: list[dict], today: datetime.date | None = None) -> dict:
    """{"groups": [[numbers in order]], "rewrite": [numbers with no files area], "waits": {number: flag}, "models": {number: (builder, QA)}}.
    Stories that share a file sit in one group in priority order, and different groups run in parallel."""
    todo = [i for i in issues if "work type: epic" not in (i.get("body") or "").lower() and "epic" not in {
        (l.get("name") if isinstance(l, dict) else l or "").lower() for l in i.get("labels") or []}]
    areas = {i["number"]: files_area(i.get("body") or "") for i in todo}
    rank = {i["number"]: (priority_of(i), i["number"]) for i in todo}
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


def open_stories(slug):
    """{number: {title, body, labels}} of the repo's open issues, over REST."""
    done = subprocess.run(["gh", "api", f"repos/{slug}/issues?state=open&per_page=100", "--paginate", "--jq",
                           '.[] | select(has("pull_request") | not) | {number, title, body, labels: [.labels[].name]}'],
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(f"could not read the open issues of {slug}")
    return {o["number"]: o for o in (json.loads(l) for l in done.stdout.splitlines() if l.strip())}


RELATED = re.compile(r"^Related:.*$", re.M)
PATH_LIKE = re.compile(r"[/.]")


def related_to(body, stories):
    """Numbers of the open stories whose Files area shares a file or folder with this body's (#1004). No model call."""
    mine = files_area(body)
    return sorted(n for n, s in stories.items() if overlaps(mine, files_area(s.get("body") or "")))


def tracked(root):
    """Every file and folder path on main, or None when git cannot read main."""
    from lib import maintain  # maintain imports intake
    ran = maintain._git(root, "ls-tree", "-r", "--name-only", "main")
    if ran.returncode:
        return None
    paths = set()
    for line in ran.stdout.splitlines():
        parts = line.split("/")
        paths.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return paths


def missing(body, on_main):
    """The Files area paths that are not on main and that no Creates line names (#1004). A word with no slash or dot is not a path."""
    made = {p.rstrip("/") for p in creates(body)}
    return [p for p in files_area(body) if PATH_LIKE.search(p) and p.rstrip("/") not in on_main and p.rstrip("/") not in made]


def fit(body, title, stories, root):
    """(the body, the lines to print) at filing (#1004). Open stories that share a Files area path get one Related line, which replaces an
    earlier one. Each named path that is not on main and not created prints with the story's title. Filing goes on either way."""
    numbers = related_to(body, stories)
    if numbers:
        line = "Related: " + ", ".join(f"#{n}" for n in numbers) + " (Files area overlaps)"
        body = RELATED.sub(line, body) if RELATED.search(body) else body.rstrip("\n") + "\n" + line + "\n"
    on_main = tracked(root)
    if on_main is None:
        return body, [f"{title}: the Files area check did not run, because git cannot read main"]
    return body, [f"{title}: Files area names {p}, which is not on main and no Creates line names it" for p in missing(body, on_main)]


def command_fit(argv):
    """`olivercode board fit BODY_FILE --title TITLE --config FILE` (#1004): rewrites BODY_FILE with its Related line and prints each
    missing path. It calls no model and returns 0 on a finding too, since the story still files."""
    opts = dict(zip(argv[1::2], argv[2::2]))
    if len(argv) != 5 or argv[0].startswith("--") or set(opts) != {"--title", "--config"}:
        print("Usage: olivercode board fit BODY_FILE --title TITLE --config FILE")
        return 1
    config = Path(opts["--config"])
    cfg = json.loads(config.read_text(encoding="utf-8"))
    slug, root = f"{cfg['repoOwner']}/{cfg['repoName']}", config.resolve().parent.parent
    path = Path(argv[0])
    try:
        stories = open_stories(slug)
    except RuntimeError as exc:
        print(f"{opts['--title']}: the Related check did not run ({exc}), so the story files without it")
        return 0
    body, lines = fit(path.read_text(encoding="utf-8"), opts["--title"], stories, root)
    path.write_text(body, encoding="utf-8")
    for line in lines:
        print(line)
    return 0


def render(found: dict) -> str:
    lines = [f"Parallel group {k}: " + " then ".join(f"#{n} ({found['models'][n][0]} builder, {found['models'][n][1]} QA, chosen for {found['models'][n][2]})" for n in g)
             for k, g in enumerate(found["groups"], 1)]
    lines += [f"#{n} names no files area: rewrite it, it is not dispatched" for n in found["rewrite"]]
    lines += [f"#{n} {why}" for n, why in sorted(found["waits"].items())]
    return "\n".join(lines) or "No open stories to split."
