"""What drain, dispatch and filing read from a story: its Size and Priority, its Files area, the filing fit check (#1004), the
repeated-blocker report and bug intake (#1371). Only bug intake files a story, and only for a fault in OliverCode's own code (#1275). Standard library only."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from lib import agent_loop, failure_log, open_issues
from lib.local_config import OC_ROOT, backlog_config, has_backlog_config
from lib import gitfiles

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))

SECURITY = re.compile(r"secret|credential|leak|vulnerab|security|data loss|lose data|lost data", re.I)
DEFECT = re.compile(r"\b(bug|broken|fails?|failing|crash|regress\w*|wrong)\b", re.I)
SIZES = ((500, "XS"), (1000, "S"), (2000, "M"), (4000, "L"))
FIELDS_LINE = r"^(?=(?:Priority|Size|Work type):)"  # a story's own fields start their line; quoted ones sit inside a scenario (#1514)


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
    """The Size the fields line states, else the first one the body states, else one by the length of its body."""
    body = story.get("body") or ""
    size = r"Size:\s*(XS|S|M|L|XL)\b"
    if m := re.search(FIELDS_LINE + ".*?" + size, body, re.M) or re.search(size, body):
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
    repeats = failure_log.repeated() if repeats is None else repeats
    return [f"{gate}: {reason}"[:100] + f" blocked {len(times)} times, latest {times[-1]}"
            for (gate, reason), times in sorted(repeats.items()) if guard_exists(gate)]


# Split open stories by files area so non-overlapping stories go to builders in parallel (#794).
AREA = re.compile(r"^\W*Files area:\W*(.+)$", re.I | re.M)
CREATES = re.compile(r"^\W*Creates:\W*(.+)$", re.I | re.M)
REMOVES = re.compile(r"^\W*Removes tests:(.*)$", re.I | re.M)
WAIT_LINE = re.compile(r"\b(?:wait\w*|until|after|once|data|window)\b", re.I)
WAIT_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
WAIT_SPAN = re.compile(r"\b(\d+)[- ]days?\s+(?:of\s+)?(?:data|window|wait)|\bwait\w*\s+(?:for\s+)?(\d+)\s+days?\b", re.I)
WAIT_DAYS = 14


def _tokens(text: str) -> list[str]:
    return [t.strip("`.,;*()") for t in re.split(r"[,;\s]+", text) if t.strip("`.,;*()")]


def _listed(line: re.Pattern, body: str) -> list[str]:
    m = line.search(body or "")
    return _tokens(m.group(1)) if m else []


def files_area(body: str) -> list[str]:
    """The paths on the story's `Files area:` line, or [] when it has none."""
    return _listed(AREA, body)


def removed_tests(body: str) -> list[str]:
    """The `file::test` names on the story's `Removes tests:` lines, the tests it removes by design (#1484), or [] when it has none."""
    return [t for line in REMOVES.findall(body or "") for t in _tokens(line) if "::" in t]


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
    ran = gitfiles.run(root, "ls-tree", "-r", "--name-only", "main")
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


# Bug intake (#1371): a failure OliverCode's own code caused becomes one story, once a fresh reader has checked it. The failure log is no source, since its gate blocks are the
# gates working; the hook-crash rows are the one exception. Every signature is read once and kept in bug-seen.json with the reader's verdict.
DAILY_CAP = 3
MAX_READS = 3
LOG_LINES = 40  # the end of a failing CI job's log, which is where the failure is (#1483)
CRASH = re.compile(r"^(Drain blocked: (the worker crashed|the landing queue crashed|The model finished, but nothing checked)|Close refused:)")
BUG_BRIEF = ("You are a fresh reader of one failure OliverCode found. Read it against this checkout with Read, Grep and Glob, and change nothing. Open the files the failure "
             "names before you decide: a doubt you did not check is not an answer. Reply with the first line being exactly one of: BUG, REGRESSION, COVERED #<number> (an open story "
             "already covers it), or NOT A BUG. A feature, cleanup, refactor or new gate is NOT A BUG. For BUG or REGRESSION write the story after the first line: a line `Title: <short title>`, "
             "then `**As the owner**, I want ..., so that ...`, a gherkin block, `Root cause: <file and line>`, the smallest change that fixes the cause (removing or reusing code before adding any), "
             "`Existing coverage checked: <what you searched>`, `Size: XS|S|M. Work type: Story.` and `Files area: <five files at most, not folders>`. No scenario sets a line-count target, and the title and story sentence of an M story never ask to remove, cut, shrink, merge or consolidate code. Leave out the Epic, Blocked by and Priority lines, "
             "which the runner adds. For the other answers give one sentence why. " + agent_loop.VERDICT_FIRST + "\n\n{task}{diff}{tail}")


def seen_path() -> Path:
    return failure_log.home() / "bug-seen.json"


def signature(kind: str, text: str) -> str:
    """One signature for failures that differ only in a worktree path, hex of 7 or more characters or a number."""
    flat = re.sub(r"\d+", "N", re.sub(r"\b[0-9a-f]{7,}\b", "H", re.sub(r"\S*_worktrees/\S*", "W", text)))
    return f"{kind}:{hashlib.sha1(flat.encode()).hexdigest()[:12]}"


def read_seen() -> dict:
    """bug-seen.json: {'created': stamp, 'seen': {signature: entry}}. It is made on the first read, so the first run reads only what was written after it."""
    try:
        data = json.loads(seen_path().read_text(encoding="utf-8"))
        if isinstance(data.get("seen"), dict):
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {"created": failure_log.stamp(), "seen": {}}


def run_candidates(rows: list[dict], repo: str = "") -> list[dict]:
    """Stopped rows of the run log that a crash, a fatal stop or a refused close wrote, for REPO's drain when it is named. A failed test, a cap, a held review, a policy stop and the usage limit never match."""
    return [{"sig": signature("drain", r["reason"]), "at": r.get("at", ""), "branch": "", "text": f"A drain stopped story {r.get('story')}: {r['reason']}"}
            for r in rows if (not repo or r.get("repo") == repo) and r.get("stage") == "stopped" and CRASH.match(str(r.get("reason") or ""))]


def hook_candidates(repo: str = "") -> list[dict]:
    return [{"sig": signature("hook", reason), "at": when, "branch": "", "text": f"A guard raised and failed open: {reason}"}
            for when, where, gate, reason in failure_log.entries() if gate == "hook-crash" and (not repo or where == repo)]


def api_json(gh, path: str) -> dict:
    """The JSON object at a REST path, or {} when the read fails."""
    done = gh([path])
    try:
        return json.loads(done.stdout) if done.returncode == 0 else {}
    except ValueError:
        return {}


def failed_ci_run(slug: str, gh, branch: str = "staging", runs: int = 1) -> dict:
    """The newest completed CI run on the branch when the newest `runs` of them all failed, else {}. A failed read is {} too."""
    found = api_json(gh, f"repos/{slug}/actions/runs?branch={branch}&status=completed&per_page={runs}").get("workflow_runs") or []
    return found[0] if len(found) >= runs and all(r.get("conclusion") == "failure" for r in found) else {}


def ci_candidate(slug: str, gh, branch: str = "staging") -> dict | None:
    """The newest completed CI run on the repo's engine branch when it failed, keyed by its failing job and step."""
    run = failed_ci_run(slug, gh, branch)
    if not run:
        return None
    bad = next((j for j in api_json(gh, f"repos/{slug}/actions/runs/{run['id']}/jobs").get("jobs") or [] if j.get("conclusion") == "failure"), {})
    step = next((s.get("name") for s in bad.get("steps") or [] if s.get("conclusion") == "failure"), "")
    key = f"{slug} {bad.get('name', 'unknown')} / {step or 'unknown'}"
    log = gh([f"repos/{slug}/actions/jobs/{bad['id']}/logs"]) if bad.get("id") else None
    tail = "\n".join(log.stdout.splitlines()[-LOG_LINES:]) if log and log.returncode == 0 else ""
    return {"sig": signature("ci", key), "at": run.get("created_at", ""), "branch": branch,
            "text": f"CI on {branch} failed ({run.get('html_url', '')}).\n- Job: {bad.get('name', 'unknown')}\n- Failing step: {step or 'unknown'}\n\n"
                    f"The last {LOG_LINES} lines of the job's log:\n{tail or '(the log could not be read)'}"}


def parse(text: str) -> tuple[str | None, str]:
    """(answer, rest) from the reader's reply: 'bug', 'regression', 'covered #N' or 'not a bug', and the text after the verdict line. None when the reply gives no verdict (#1483)."""
    word, rest = agent_loop.verdict_line(text, r"bug|regression|covered\b[^#]*#\d+|not a bug")
    if not word:
        return None, rest
    if word.startswith("covered"):
        return "covered " + re.search(r"#\d+", word).group(0), rest
    return next((a for a in ("bug", "regression") if word.startswith(a)), "not a bug"), rest


def story_text(rest: str, candidate: dict, epic: int) -> tuple[str, str]:
    """(title, body): the reader's story with the lines the runner owns: the second-opinion result, a Fit line when the reader wrote none,
    Epic, Blocked by and Priority, P1 for CI on the engine branch and P2 otherwise."""
    title = re.search(r"^Title:\s*(.+)$", rest, re.M)
    body = re.sub(r"^Title:.*\n?", "", rest, flags=re.M).strip()
    body = re.sub(r"^(\W*Existing coverage checked:.*)$", r"\1 Second opinion skipped: bug intake's one fresh reader wrote this story.", body, count=1, flags=re.M)
    if not re.search(r"^\W*Fit:", body, re.M):
        body += "\n\nFit: the smallest change at the root cause, in the code that exists."
    tail = f"\n\nEpic: #{epic}\nBlocked by: none.\nPriority: {'P1' if candidate['branch'] else 'P2'}.\n\nFound by bug intake ({candidate['sig']}):\n{candidate['text']}\n"
    return (title.group(1).strip() if title else "Fix a failure OliverCode found")[:120], body + tail


def file_story(slug: str, root: Path, title: str, body: str, gh) -> int | None:
    """Create the issue over REST and queue its card for Ready. Returns its number, or None when it was not created."""
    done = gh(["-X", "POST", f"repos/{slug}/issues", "-f", f"title={title}", "-f", f"body={body}"])
    try:
        n = int(json.loads(done.stdout)["number"]) if done.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        return None
    if n:
        from lib import cmd_dispatch  # local import: cmd_dispatch loads the modules that import this one
        cfg = backlog_config(root)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "Ready"}}]}]))
    return n


def own_code(root: Path, rest: str) -> bool:
    """True when the story's Root cause line names a file of OliverCode's own checkout, which a drain of another repo does not hold."""
    m = re.search(r"^Root cause:\s*`?([^\s`:]+)", rest, re.M)
    if not m or agent_loop.is_engine_repo(root):
        return False
    path = Path(m.group(1))
    if path.is_absolute():
        return OC_ROOT in path.parents and root not in path.parents
    return (OC_ROOT / path).exists() and not (root / path).exists()


def destination(where: Path, root: Path) -> tuple[str, int] | None:
    """(repo slug, error epic) a story files under: ROOT's own repo, or the origin of the user's OliverCode checkout for a fault in OliverCode's code. None when no epic is named."""
    cfg = backlog_config(where)
    epic = cfg.get("errorEpic")
    slug = agent_loop.origin_of(where) if where != root else f"{cfg['repoOwner']}/{cfg['repoName']}"
    return (slug, int(epic)) if slug and isinstance(epic, int) else None


def bugs(root: Path = OC_ROOT, gh=None, read=agent_loop.review, now: datetime.datetime | None = None, say=print) -> int:
    """Read the new candidates (a drain stop, red CI on staging, a hook crash) with a fresh reader and file a story for each bug or regression. Returns how many stories were filed.
    A signature already in bug-seen.json starts no reader: a covered, not-a-bug or filed one is skipped, a recurrence of a closed story reopens it, and a bug the daily cap held is filed."""
    from check_story_format import check_body  # noqa: PLC0415
    if not has_backlog_config(root):
        say(f"Bug intake files nothing for {root.name}: it has no docs/backlog-config.json.")
        return 0
    own = destination(root, root)
    if not own:
        say(f"Bug intake files nothing for {root.name}: its backlog config names no errorEpic.")
        return 0
    slug, _ = own
    branch = agent_loop.default_branch(root)
    gh = gh or (lambda args: subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60))
    opened = open_issues.fetch(slug)
    if opened is None:
        return 0  # GitHub is held or unreadable, so the next run reads again
    data = read_seen()
    seen, today = data["seen"], (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%d")
    open_numbers = {i["number"] for i in opened}
    filed = sum(1 for e in seen.values() if e.get("filed_on") == today)

    def file_entry(sig: str, entry: dict) -> bool:
        nonlocal filed
        where = Path(entry.get("repo") or root)
        if filed >= DAILY_CAP or not (dest := destination(where, root)) or not (n := file_story(dest[0], where, entry["title"], entry["body"], gh)):
            return False
        entry.update(story=n, filed_on=today)
        filed += 1
        return True

    new = 0
    for sig, entry in seen.items():  # a bug the cap held waits in bug-seen.json until the next day
        if entry["verdict"] in ("bug", "regression") and not entry.get("story"):
            new += file_entry(sig, entry)
    rows = []
    for l in agent_loop.run_log_lines():
        if l.startswith("{"):
            try:
                rows.append(json.loads(l))
            except ValueError:
                pass  # a half-written last line
    ci = ci_candidate(slug, gh, branch)
    reads = 0
    for c in [*run_candidates(rows, root.name), *hook_candidates(root.name), *([ci] if ci else [])]:
        entry = seen.get(c["sig"])
        if c["at"] < data["created"]:
            continue  # written before bug-seen.json was made, so it is never read
        if entry:
            if entry.get("story") and entry["story"] not in open_numbers and c["at"] > entry.get("at", ""):
                gh(["-X", "PATCH", f"repos/{slug}/issues/{entry['story']}", "-f", "state=open"])
                gh(["-X", "POST", f"repos/{slug}/issues/{entry['story']}/comments", "-f", f"body=This failure came back ({c['sig']}):\n{c['text']}"])
                entry["at"] = c["at"]
            continue
        if reads >= MAX_READS:
            break
        reads += 1
        titles = "\n".join(f"- #{i['number']} {i.get('title', '')}" for i in opened)
        reply = read(f"The failure:\n{c['text']}\n\nOliverCode's own code is at {OC_ROOT}.\n\nThe open stories:\n{titles}\n", root, "bug-intake", "", brief=BUG_BRIEF, say=say)
        if reply["verdict"] == "none":
            continue  # no answer, so nothing is recorded and the next run reads it again
        answer, rest = parse(reply["text"])
        if answer is None:
            continue  # the reader gave no verdict, so nothing is recorded and the next run reads it again (#1483)
        entry = seen[c["sig"]] = {"verdict": answer.split()[0] if answer != "not a bug" else "not a bug", "at": c["at"]}
        if answer.startswith("covered"):
            number = int(answer.split("#")[1])
            entry["story"] = number
            gh(["-X", "POST", f"repos/{slug}/issues/{number}/comments", "-f", f"body=Another occurrence of a failure this story covers ({c['sig']}):\n{c['text']}"])
        elif answer != "not a bug":
            where = OC_ROOT if own_code(root, rest) else root
            if not (dest := destination(where, root)):
                continue  # the checkout's config names no errorEpic, so nothing is filed or recorded
            entry["repo"] = str(where)
            entry["title"], entry["body"] = story_text(rest, c, dest[1])
            if check_body(entry["body"], files=True, blocker=True, root=where, fit=True, title=entry["title"]):
                entry["verdict"] = "not a bug"  # a story that fails the format check is never filed
                continue
            new += file_entry(c["sig"], entry)
    try:
        failure_log.write_private(seen_path(), json.dumps(data, indent=1))
    except OSError:
        pass
    return new
