"""Launcher command `board groom`: fixes drifted and missing board cards (#660) and fills the rest of the grooming (#724).
`olivercode board groom [--config FILE | --all | --force]` calls no model; a repo unchanged since the last run costs no GraphQL call.

Beyond drift it sets a blank Priority and Size from the story body, moves an unblocked Backlog story that has both to
Ready, closes an exact duplicate (same title and Files area) as a duplicate of the older story (#1100), links each other duplicate pair that shares a Files area with a comment on each story naming the one to keep (#1089), and queues one owner line for each weaker pair and each story whose criteria already appear in the repo (#1100). It also does the work of the retired board sweep: it reads each board for drift, runs the intake check and files the repeated-blocker story (#982). It reopens each story at or above `closeGateFromIssue` that was closed without complete_story.py's evidence, moves it to Backlog and asks the owner whether to run complete_story.py on it (#1104). `maintain --fix` runs it, the
SessionStart hook starts it in the background when the last success is over 24 hours old, and `health` fails after 48.

A story imported from a file (a `Source:` line naming one) carries a copied Priority, so groom labels it
priority-not-reviewed and files one rerank story for all of them (#743). Once that story closes, the label on each story it
covered becomes priority-reviewed.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lib import cmd_owner, failure_log, gh_budget, maintain, name_drift, rename_check
from lib.cmd_sweep import boards
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))


_state = lambda: failure_log.home() / "groom-state.json"  # noqa: E731


def load_state():
    try:
        return json.loads(_state().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


GH_FALLBACK = "/opt/homebrew/bin/gh"  # launchd's default PATH has no gh, so the job falls back to the Homebrew folder (#1010)


def put_gh_on_path():
    """Adds the Homebrew folder to PATH when gh is not on it, so every subprocess this run starts (the skill scripts and the rate-limit reads too) finds gh (#1010)."""
    if shutil.which("gh") is None and Path(GH_FALLBACK).is_file():
        os.environ["PATH"] = os.pathsep.join([str(Path(GH_FALLBACK).parent), os.environ.get("PATH", "")])


def gh(args):
    done = subprocess.run([shutil.which("gh") or GH_FALLBACK, *args], capture_output=True, text=True, timeout=120)
    return done.stdout if done.returncode == 0 else None


def fingerprint(slug, root, run=gh):
    newest = (run(["api", f"repos/{slug}/issues?state=all&sort=updated&direction=desc&per_page=1", "--jq", ".[0].updated_at"]) or "").strip()
    heads = maintain._git(root, "ls-remote", "--heads", "origin").stdout
    return f"{newest}|{hashlib.sha1(heads.encode()).hexdigest()[:12]}" if newest else ""


SECURITY = re.compile(r"secret|credential|leaked|leak(?:s|ing)? (?:a |the |an )?(?:key|token|secret|password|credential)|vulnerab|security|data loss|lose data|lost data", re.I)
DEFECT = re.compile(r"\b(bug|broken|fails?|failing|crash|regress\w*|wrong)\b", re.I)
BLOCKED = re.compile(r"blocked by|depends on #|needs a decision|waiting on", re.I)
HELD_LABELS = {"owner-action", "blocked"}
SIZES = ((3, "XS"), (5, "S"), (8, "M"), (12, "L"))  # files plus scenarios, up to each limit (#1091)
FRESH_HOURS, STALE_HOURS = 24, 48


def open_stories(slug, run=gh):
    """{number: {title, body, labels}} of the repo's open issues."""
    raw = run(["api", f"repos/{slug}/issues?state=open&per_page=100", "--paginate", "--jq",
               '.[] | select(has("pull_request") | not) | {id, number, title, body, labels: [.labels[].name], issue_dependencies_summary}'])
    if raw is None:
        raise RuntimeError(f"could not read the open issues of {slug}")
    return {o["number"]: o for o in (json.loads(l) for l in raw.splitlines() if l.strip())}


def priority_of(story):
    """The stated Priority, else the level suggested by the written scale."""
    if m := re.search(r"Priority:\s*(P[012])\b", story.get("body") or ""):
        return m.group(1)
    return suggested_priority(story)


def suggested_priority(story):
    """The level the title and body suggest, without changing the story's line."""
    text = f"{story.get('title') or ''}\n{story.get('body') or ''}"
    return "P0" if SECURITY.search(text) else "P1" if DEFECT.search(text) else "P2"


def priority_mismatches(stories):
    """Report stated priorities lower than the written scale suggests."""
    found = []
    for number, story in sorted(stories.items()):
        # shortcut: the board's Ready state is not read here, so held and blocked stories are skipped, upgrade when Ready is available
        if HELD_LABELS & set(story.get("labels") or []) or BLOCKED.search(story.get("body") or ""):
            continue
        stated = re.search(r"Priority:\s*(P[012])\b", story.get("body") or "")
        if stated and stated.group(1) > suggested_priority(story):
            found.append(f"#{number} states {stated.group(1)} but the scale suggests {suggested_priority(story)}")
    return found


def size_of(story):
    """The Size line the story states, else one from the files it names (Files area and Creates) plus its scenarios, never the length of its body (#1091)."""
    from lib import intake
    body = story.get("body") or ""
    if m := re.search(r"Size:\s*(XS|S|M|L|XL)\b", body):
        return m.group(1)
    count = len(set(intake.files_area(body)) | set(intake.creates(body))) + len(re.findall(r"^\s*Scenario(?: Outline)?:", body, re.M))
    return next((name for limit, name in SIZES if count <= limit), "XL")


SPLIT_TITLE = "Split #{n} into smaller stories"
SPLIT_BODY = """**As the owner**, I want #{n} split into smaller stories, so that no builder session starts a story it cannot finish.

```gherkin
Feature: Split an oversized story
  Scenario: Main case
    Given #{n} is judged {size} from its Files area and scenarios and waits in Backlog
    When its parts are filed, each naming `Split from #{n}` and sized XS, S or M
    Then `{command}` leaves #{n} alone and the parts build in its place
```

Epic: #{epic}
Priority: P1. Size: S. Work type: Story.

Existing coverage checked: groom found #{n} oversized and held it in Backlog until its parts exist.
"""


def oversized(items, stories):
    """Numbers of open stories judged L or XL that are not epics and have no part filed yet (a story naming `Split from #N`), so they wait in Backlog (#1091)."""
    import board_grooming
    carded = {(i.get("content") or {}).get("number"): i for i in items}
    epic = lambda n, s: str(board_grooming.field(carded.get(n, {}), "work type") or "").lower() == "epic"  # noqa: E731
    parts = {int(n) for s in stories.values() if not (s.get("title") or "").startswith("Split #") for n in re.findall(r"Split from #(\d+)", s.get("body") or "")}
    return {n for n, s in stories.items() if size_of(s) in ("L", "XL") and not epic(n, s) and n not in parts}


def file_splits(slug, config, stories, big, epic=1, file=None, queued=None):
    """File one audit story, with the groom command that re-checks it, for each oversized story that has none open or queued. Returns the numbers filed."""
    from lib import intake
    file = file or intake.candidate
    filed = []
    for n in sorted(big):
        title = SPLIT_TITLE.format(n=n)
        if any(s.get("title") == title for s in stories.values()) or (queued and queued(slug, title)):
            continue
        file(slug, title, SPLIT_BODY.format(n=n, size=size_of(stories[n]), epic=epic, command=f"olivercode board groom --config {config}"))
        filed.append(n)
    return filed


def comment_oversized(slug, big_ready, stories, mine, run=gh):
    """One comment on each Ready oversized story saying its move to Backlog and that it must be split, posted once per story (#1132)."""
    done = mine.setdefault("big_commented", [])
    commented = []
    for n in sorted(big_ready):
        if n in done:
            continue
        text = (f"Moved to Backlog: Size {size_of(stories[n])} is too large for one builder session, so it never reaches the runner. "
                "Split it into thin stories under its epic, then return it to Ready.")
        if say(slug, n, text, run):
            done.append(n)
            commented.append(n)
    return commented


def epic_priority(story, stories, carded):
    """The Priority of the story's epic when the story states none (#1099): the epic's card, else the line in its body."""
    import board_grooming
    n = board_grooming.epic_of(story.get("body") or "")
    if n is None or STATED.search(story.get("body") or ""):
        return None
    epic = (carded.get(n) or {}).get("priority")
    if epic:
        return epic
    m = re.search(r"Priority:\s*(P[012])\b", (stories.get(n) or {}).get("body") or "")
    return m.group(1) if m else None


def filled(items, stories, fixes, hold=frozenset(), split=frozenset()):
    """Merge into `fixes` a Priority and Size for each open story that lacks one and a move to Ready for each unblocked Backlog story that `hold` does not name,
    so a flagged story waits in Backlog for the owner (#1014). A Ready story in `split` moves to Backlog (#1091)."""
    import board_grooming
    by = {f["number"]: f for f in fixes}
    carded = {(i.get("content") or {}).get("number"): i for i in items}
    for number, story in sorted(stories.items()):
        card = carded.get(number, {})
        want = {}
        if not card.get("priority"):
            want["priority"] = epic_priority(story, stories, carded) or priority_of(story)
        if not card.get("size"):
            want["size"] = size_of(story)
        status = by.get(number, {}).get("fields", {}).get("status") or card.get("status") or "Backlog"
        epic = str(board_grooming.field(card, "work type") or "").lower() == "epic"
        held = HELD_LABELS & set(story.get("labels") or []) or BLOCKED.search(story.get("body") or "")
        if status == "Backlog" and not epic and not held and number not in hold:
            want["status"] = "Ready"
        elif status == "Ready" and number in split:
            want["status"] = "Backlog"
        if want:
            by.setdefault(number, {"number": number, "fields": {}})["fields"].update(want)
    return sorted(by.values(), key=lambda f: f["number"])


IMPORTED = re.compile(r"\bSource:[^\n]*?[\w.-]+\.(?:md|txt|csv|json|ya?ml)\b", re.I)
STATED = re.compile(r"\bPriority:\s*P[012]\b")
FLAG, REVIEWED = "priority-not-reviewed", "priority-reviewed"
RERANK = re.compile(r"^Rerank \d+ imported priorities against the code$")
RERANK_TITLE = "Rerank {n} imported priorities against the code"
RERANK_BODY = """**As the owner**, I want the priorities copied in from a file judged against the code, so that I never have to ask for it.

```gherkin
Feature: Have imported priorities judged against the code
  Scenario: Main case
    Given {n} open stories whose Priority was copied from a file: {numbers}
    When each Priority is checked against the code and set on the story and its card
    Then this story closes and groom replaces priority-not-reviewed with priority-reviewed on each
```

Epic: #{epic}
Priority: P2. Size: S. Work type: Story.

Existing coverage checked: groom already flags priority-not-reviewed, and this story reviews the flagged stories.
"""


def imported(stories):
    """Numbers of open stories whose Priority was copied from a file and has not been reviewed since."""
    return sorted(n for n, s in stories.items() if IMPORTED.search(s.get("body") or "") and STATED.search(s.get("body") or "")
                  and REVIEWED not in (s.get("labels") or []) and not RERANK.match(s.get("title") or ""))


def _queued(slug, title):
    """True when the story waits in the candidates list or the story outbox."""
    from lib import candidates
    return candidates.has(slug, title)


def review_imported(slug, stories, mine, epic=1, run=gh, file=None, queued=None):
    """Flag each imported story priority-not-reviewed and file one rerank story; clear the flags its closing covers.
    Returns an owner line, or "" when nothing changed. `mine["rerank"]` holds the numbers the rerank story covers."""
    from lib import intake
    file = file or intake.candidate

    def edit(number, *args):
        if run(["issue", "edit", str(number), "--repo", slug, *args]) is None:
            raise RuntimeError(f"could not relabel #{number}")

    def label(name, about):
        run(["label", "create", name, "--repo", slug, "--force", "--color", "FBCA04", "--description", about])

    lines, rerank = [], mine.get("rerank") or {}
    open_rerank = any(RERANK.match(s.get("title") or "") for s in stories.values())
    if rerank and open_rerank:
        rerank["seen"] = True
    if queued and rerank and not rerank.get("seen") and not open_rerank and not queued(slug, RERANK_TITLE.format(n=len(rerank.get("numbers", [])))):
        mine.pop("rerank", None)  # the candidate was dropped and no story is open, so refile it if still needed (#1024)
        rerank = {}
    if rerank.get("seen") and not open_rerank:
        label(REVIEWED, "Priority judged against the code after an import")
        done = [n for n in rerank.get("numbers", []) if n in stories]
        for n in done:
            edit(n, "--remove-label", FLAG, "--add-label", REVIEWED)
            stories[n]["labels"] = [l for l in stories[n].get("labels") or [] if l != FLAG] + [REVIEWED]
        mine.pop("rerank", None)
        rerank = {}
        lines.append(f"the rerank closed, so {len(done)} imported priorities are marked reviewed")
    todo = imported(stories)
    fresh = [n for n in todo if FLAG not in (stories[n].get("labels") or [])]
    if fresh:
        label(FLAG, "Priority copied from an import, not yet judged against the code")
        for n in fresh:
            edit(n, "--add-label", FLAG)
            stories[n]["labels"] = list(stories[n].get("labels") or []) + [FLAG]
        lines.append(f"{len(fresh)} imported priorities flagged as not reviewed")
    if todo and not rerank and not open_rerank:
        file(slug, RERANK_TITLE.format(n=len(todo)), RERANK_BODY.format(n=len(todo), numbers=", ".join(f"#{n}" for n in todo), epic=epic))
        mine["rerank"] = {"numbers": todo, "seen": False}
        lines.append(f"one rerank candidate added for {len(todo)}")
    return "; ".join(lines)


def carded_status(items, number):
    """The board status of the card for this story number, or ""."""
    return next((i.get("status") or "" for i in items if (i.get("content") or {}).get("number") == number), "")


def board_grooming_field(item, name):
    import board_grooming
    return board_grooming.field(item, name)


def duplicates(items):
    import board_grooming
    return board_grooming.overlapping_titles(items, {"Backlog", "Ready", "In Progress"})


def exact_duplicates(stories):
    """[(newer, older, shared files)] for open stories with the same title, ignoring case and spacing, and the same non-empty Files area (#1100).
    Every weaker match stays a line for the owner. Each newer story pairs with the oldest story it copies."""
    from lib import intake
    seen, found = {}, []
    for n, s in sorted(stories.items()):
        files = sorted(set(intake.files_area(s.get("body") or "")))
        key = (" ".join((s.get("title") or "").lower().split()), tuple(files))
        if files and key in seen:
            found.append((n, seen[key], files))
        elif files:
            seen[key] = n
    return found


def close_duplicates(slug, stories, run=gh):
    """Closes each exact duplicate as a duplicate of the older story, with a comment that names it, the shared files and the reopen command.
    The issue is closed, never deleted. Returns the numbers closed; a story whose comment or close fails stays open."""
    closed = []
    for newer, older, files in exact_duplicates(stories):
        note = (f"Closed as an exact duplicate of #{older}: same title and the same files ({', '.join(files)}). "
                f"To reopen: `gh api -X PATCH repos/{slug}/issues/{newer} -f state=open`")
        if run(["api", f"repos/{slug}/issues/{newer}/comments", "-f", f"body={note}"]) is None:
            continue
        if run(["api", "-X", "PATCH", f"repos/{slug}/issues/{newer}", "-f", "state=closed", "-f", "state_reason=duplicate"]) is not None:
            closed.append(newer)
    return closed


def as_process(run):
    """The groom's `gh` (stdout, or None on failure) as the CompletedProcess the close-gate read takes, with `api` added (#1104)."""
    def runner(args):
        out = run(["api", *args])
        return subprocess.CompletedProcess(args, 0 if out is not None else 1, out or "", "" if out is not None else "gh api failed")
    return runner


def reopen_unproven(slug, found, run=gh):
    """Reopens each closed story that complete_story.py never closed (#1104), with a comment naming the missing evidence. `found` is the
    (number, title) pairs from check_board_hygiene.unproven_closes. Returns the numbers reopened; one whose comment or reopen fails stays closed."""
    reopened = []
    for number, _ in found:
        note = ("Reopened: this story was closed without complete_story.py, so no comment ends with `Closed by complete_story.py.` "
                "The missing evidence is that comment's run output and Live line. "
                f"To close it with its evidence, run `complete_story.py --story {number} --config CONFIG --evidence TEXT`.")
        if run(["api", f"repos/{slug}/issues/{number}/comments", "-f", f"body={note}"]) is None:
            continue
        if run(["api", "-X", "PATCH", f"repos/{slug}/issues/{number}", "-f", "state=open"]) is not None:
            reopened.append(number)
    return reopened


def _read_or_raise(run):
    """A reader that raises on a failed read, so groom records a failure instead of treating a missing answer as none (#1105)."""
    def read(args):
        out = run(args)
        if out is None:
            raise RuntimeError("could not read the sub-issues of the epics")
        return out
    return read


def _close_epic(slug, number, run=gh):
    """Closes an epic whose sub-issues are all closed, so its Complete card and its open issue do not disagree (#853, #1105). False when the close fails."""
    return run(["api", "-X", "PATCH", f"repos/{slug}/issues/{number}", "-f", "state=closed", "-f", "state_reason=completed"]) is not None


CRITERION = re.compile(r"^\s*(?:Then|And)\s+(.{30,})$", re.M)


def code_overlaps(stories, root):
    """One line per story whose Then or And criterion text is already a line on main, naming the file and line (#1100). A story with Creates
    lines is skipped, since it says the work is new. Returns [] when git cannot search main."""
    from lib import intake
    lines = []
    for n, s in sorted(stories.items()):
        body = s.get("body") or ""
        block = re.search(r"```gherkin(.*?)```", body, re.S)
        wanted = [m.strip() for m in CRITERION.findall(block.group(1))] if block else []
        if not wanted or intake.creates(body):
            continue
        ran = maintain._git(root, "grep", "-n", "-F", "-i", "-m", "1", *[a for w in wanted for a in ("-e", w)], "main", "--", ":!*.json")
        hit = ran.stdout.splitlines()[0] if ran.returncode == 0 and ran.stdout else ""
        if m := re.match(r"main:([^:]+):(\d+):", hit):
            lines.append(f"#{n} criteria already appear at {m.group(1)}:{m.group(2)}: check whether the story is still needed")
    return lines


def pair_numbers(pairs):
    """The story numbers named in each duplicate line, so both stories of a pair stay in Backlog (#1014)."""
    return {int(n) for pair in pairs for n in re.match(r"#(\d+) and #(\d+) share", pair).groups()}


def pair_of(line):
    """The two story numbers a duplicate line names, lower first."""
    return tuple(sorted(int(n) for n in re.match(r"#(\d+) and #(\d+) share", line).groups()))


def linked_pair(line, mine):
    """True when both stories of the pair already carry their duplicate comment (#1089)."""
    a, b = pair_of(line)
    done = mine.get("linked", {}).get(f"{a}-{b}", [])
    return a in done and b in done


def link_duplicates(slug, pairs, stories, mine, run=gh):
    """One comment on each story of a duplicate pair whose Files areas also overlap, naming the other story and the lower-numbered one to keep (#1089).
    mine["linked"] holds the numbers each pair has commented on, so a story that is already done is never commented again."""
    from lib import intake
    linked = mine.setdefault("linked", {})
    for line in pairs:
        a, b = pair_of(line)
        if a not in stories or b not in stories or not intake.overlaps(intake.files_area(stories[a].get("body") or ""), intake.files_area(stories[b].get("body") or "")):
            continue
        done = linked.setdefault(f"{a}-{b}", [])
        for n, other in ((a, b), (b, a)):
            if n in done:
                continue
            text = f"Possible duplicate of #{other}: the titles and Files areas match. Keep #{a} and close #{b}."
            if run(["api", "-X", "POST", f"repos/{slug}/issues/{n}/comments", "-f", f"body={text}"]) is not None:
                done.append(n)


def last_ok(state=None, slugs=None):
    """The oldest success time across the boards (all of `slugs`, else every repo in the state), or None when one never succeeded."""
    state = load_state() if state is None else state
    times = [state.get(s, {}).get("ok") for s in (slugs if slugs is not None else state)]
    return min(times) if times and all(times) else None


def stale(hours, now=None, state=None, slugs=None):
    """True when the oldest groom success is older than `hours` or a board has none."""
    seen = last_ok(state, slugs)
    return seen is None or (time.time() if now is None else now) - seen > hours * 3600


def queue_failure(name, slug, config, error):
    """One open owner line for a board whose groom failed, naming the error and the command that retries it (#1010). A line that already
    names the same error stays; a line with an older error closes and is replaced."""
    key, retry = f"groom:{slug}", f"olivercode board groom --config {config}"
    open_lines = [i for i in cmd_owner.items() if i["status"] == "open" and i.get("key") == key]
    if any(i.get("error") == error for i in open_lines):
        return
    for i in open_lines:
        cmd_owner.close(i["id"])
    step = f"{name} ({slug}) did not groom: fix the cause in the error, then run `{retry}`"
    try:
        cmd_owner.add("groom", step, command=retry, error=error, extra={"key": key})
    except ValueError:  # the error text held a value the owner queue refuses, so the line names the state file instead
        cmd_owner.add("groom", step, command=retry, error="the error text is not stored here; see groom-state.json", extra={"key": key})


def close_failure(slug):
    """Closes the owner line for a board that grooms again."""
    for i in cmd_owner.items():
        if i["status"] == "open" and i.get("key") == f"groom:{slug}":
            cmd_owner.close(i["id"])


EPIC_LINE = re.compile(r"^Epic:\s*#(\d+)", re.M)


def link_epics(slug, stories, items, run=gh):
    """Link each open story as a sub-issue of the epic its `Epic:` line names, so an epic shows complete only when every story under it has closed (#1109).
    Returns (linked numbers, {number: epic} whose Epic line points at something that is not an Epic). A failed read or write leaves the story for the next groom."""
    import board_grooming
    kinds = {(i.get("content") or {}).get("number"): str(board_grooming.field(i, "work type") or "").lower() for i in items}
    subs, linked, wrong = {}, [], {}
    for n, story in sorted(stories.items()):
        m = EPIC_LINE.search(story.get("body") or "")
        if not m or int(m.group(1)) == n or "id" not in story:
            continue
        epic = int(m.group(1))
        if kinds.get(epic) != "epic":
            wrong[n] = epic
            continue
        if epic not in subs:
            raw = run(["api", f"repos/{slug}/issues/{epic}/sub_issues", "--paginate", "--jq", ".[].number"])
            subs[epic] = None if raw is None else {int(x) for x in raw.split()}
        if subs[epic] is None or n in subs[epic]:
            continue
        if run(["api", "-X", "POST", f"repos/{slug}/issues/{epic}/sub_issues", "-F", f"sub_issue_id={story['id']}"]) is not None:
            subs[epic].add(n)
            linked.append(n)
    return linked, wrong


def area_fixes(items, stories, options):
    """{number: Area} for each open story whose card has no Area, from the Area the board gives each file of its Files area (#1109). A file takes the most common
    Area among the cards that list it, else the skill folder it sits in. One Area for all files gives that Area, several give "fleet-wide", none known gives nothing."""
    import board_grooming
    from collections import Counter
    from lib import intake
    carded = {(i.get("content") or {}).get("number"): i for i in items}
    seen = {}
    for n, card in carded.items():
        a = board_grooming.field(card, "area")
        for f in intake.files_area((stories.get(n) or {}).get("body") or "") if a else []:
            seen.setdefault(f, Counter())[a] += 1

    def area_of(path):
        if seen.get(path):
            return seen[path].most_common(1)[0][0]
        m = re.match(r"skills/([^/]+)/", path)
        return m.group(1) if m and m.group(1) in options else None

    found = {}
    for n, story in sorted(stories.items()):
        card = carded.get(n)
        if card is None or board_grooming.field(card, "area") or str(board_grooming.field(card, "work type") or "").lower() == "epic":
            continue
        areas = {area_of(f) for f in intake.files_area(story.get("body") or "")}
        if areas and None not in areas:
            found[n] = areas.pop() if len(areas) == 1 else "fleet-wide"
    return found


def groom_board(name: str, config: Path, force=False, now=None, run=gh):
    import batch_project
    import board_grooming
    import board_rest
    import check_board_hygiene
    now = time.time() if now is None else now
    put_gh_on_path()
    cfg = json.loads(config.read_text(encoding="utf-8"))
    slug, root = f"{cfg['repoOwner']}/{cfg['repoName']}", config.resolve().parent.parent
    state = load_state()
    mine = state.setdefault(slug, {})
    try:
        check_board_hygiene.verify_config(cfg, config)  # a fork's inherited config is never groomed (#687)
        held = gh_budget.refusal() or gh_budget.points_refusal()
        if held:
            raise RuntimeError("did not run: " + held.split(". ")[0])
        fp = fingerprint(slug, root, run)
        if fp and fp == mine.get("fp") and not force:
            print(f"{name}: unchanged since the last groom, skipped")
            mine.update(ok=now, failed="")
            close_failure(slug)
            return True
        issues = board_rest.repo_issues(slug, run)
        if issues is None:
            raise RuntimeError(f"could not read the issues of {slug}")
        states = {i["number"]: i["state"] for i in issues}
        items = check_board_hygiene.load_items(cfg)
        closed_cards = [i for i in items if states.get((i.get("content") or {}).get("number")) == "CLOSED"]
        reopened = reopen_unproven(slug, check_board_hygiene.unproven_closes(closed_cards, cfg, runner=as_process(run)), run)
        for n in reopened:
            states[n] = "OPEN"  # the drift rule below then moves its card to Backlog, and hold keeps it out of Ready
        if reopened:
            cmd_owner.note("groom", f"{name}: reopened {len(reopened)} story(ies) closed without complete_story.py evidence, now in Backlog: "
                           + ", ".join(f"#{n}" for n in reopened) + ". Run complete_story.py on them?")
        stories = open_stories(slug, run)
        from lib import intake
        found = intake.plan(list(stories.values()))
        flagged = [f"#{n} names no files area, rewrite it" for n in found["rewrite"]] + [f"#{n} {why}" for n, why in found["waits"].items()]
        closed = close_duplicates(slug, stories, run)
        for n in closed:
            stories.pop(n, None)
        if closed:
            cmd_owner.note("groom", f"{name}: closed {len(closed)} exact duplicate(s) as duplicates, reopen any with the command in its comment: " + ", ".join(f"#{n}" for n in closed))
        pairs = [p for p in duplicates(items) if not set(map(int, re.findall(r"#(\d+)", p.split(" share")[0]))) & set(closed)]
        card_epics = {(i.get("content") or {}).get("number") for i in items if str(board_grooming_field(i, "work type") or "").lower() == "epic"}
        linked, found_themes = assign_epics(slug, stories, mine, card_epics, run, str(config))
        if linked:
            cmd_owner.note("groom", f"{name}: linked {len(linked)} story(ies) to an epic, undo any with the command in its comment: " + ", ".join(f"#{n}" for n in linked))
        propose_epics(name, found_themes, stories, slug)
        overlaps = code_overlaps(stories, root)
        if overlaps and json.dumps(overlaps) != mine.get("overlaps"):
            cmd_owner.note("groom", f"{name}: {len(overlaps)} story(ies) overlap code or docs: " + "; ".join(overlaps)[:600])
        mine["overlaps"] = json.dumps(overlaps)
        big = oversized(items, stories)
        big_ready = {n for n in big if (carded_status(items, n) == "Ready")}
        if filed := file_splits(slug, config, stories, big_ready, int(cfg.get("epic") or 1), queued=_queued):
            cmd_owner.note("groom", f"{name}: {len(filed)} oversized story(ies) moved to Backlog, one split story filed for each: " + ", ".join(f"#{n}" for n in filed))
        if commented := comment_oversized(slug, big_ready, stories, mine, run):
            cmd_owner.note("groom", f"{name}: told {len(commented)} oversized story(ies) on the issue that they must be split: " + ", ".join(f"#{n}" for n in commented))
        hold = set(found["rewrite"]) | set(found["waits"]) | pair_numbers(pairs) | big | set(reopened)  # flagged stories stay in Backlog until the owner acts (#1014, #1104)
        epics = board_grooming.epic_moves(items, check_board_hygiene.epic_summaries(items, cfg, "Complete", _read_or_raise(run)), "Complete")
        moved = [m for m in epics if m[1] != "Complete" or _close_epic(slug, m[0], run)]  # an epic moves with its stories (#1105)
        moved_numbers = {n for n, _, _ in moved}
        drift = [{"number": n, "fields": {"status": "Complete" if k == "close" else "Backlog"}}
                 for n, k in check_board_hygiene.status_drift(items, states, slug) if n not in moved_numbers]
        fixes = filled(items, stories, drift + [{"number": n, "fields": {"status": s}} for n, s, _ in moved], hold, big)
        for n, area in area_fixes(items, stories, (cfg.get("fields", {}).get("area") or {}).get("options", {})).items():
            fix = next((f for f in fixes if f["number"] == n), None)
            if fix is None:
                fixes.append(fix := {"number": n, "fields": {}})
            fix["fields"]["area"] = area
        linked, wrong = link_epics(slug, stories, items, run)
        if linked:
            cmd_owner.note("groom", f"{name}: linked " + ", ".join(f"#{n}" for n in linked) + " as sub-issues of the epic each names")
        wrongs = [f"#{n} Epic line points at #{e}, which is a story" for n, e in wrong.items()]
        if wrongs and json.dumps(wrongs) != mine.get("wrong_epics"):
            cmd_owner.note("groom", f"{name}: " + "; ".join(wrongs)[:600])
        mine["wrong_epics"] = json.dumps(wrongs)
        if line := review_imported(slug, stories, mine, int(cfg.get("epic") or 1), run, queued=_queued):
            cmd_owner.note("groom", f"{name}: {line}")
        if flagged and json.dumps(flagged) != mine.get("split"):
            cmd_owner.note("groom", f"{name}: {len(flagged)} story(ies) need a rewrite before dispatch: " + "; ".join(flagged)[:600])
        mine["split"] = json.dumps(flagged)
        link_duplicates(slug, pairs, stories, mine, run)
        pairs = [p for p in pairs if not linked_pair(p, mine)]  # a linked pair already has its comments, so the owner is not asked again (#1089)
        if pairs and json.dumps(pairs) != mine.get("dups"):
            cmd_owner.note("groom", f"{name}: {len(pairs)} possible duplicate pair(s): " + "; ".join(pairs)[:600])
        mine["dups"] = json.dumps(pairs)
        renames = [f"#{n} {why}" for n, why in rename_check.missing_line(stories).items()]  # a rename story names its old name (#838)
        if renames and json.dumps(renames) != mine.get("renames"):
            cmd_owner.note("groom", f"{name}: {len(renames)} rename story(ies) name no old name: " + "; ".join(renames)[:600])
        mine["renames"] = json.dumps(renames)
        mismatches = priority_mismatches(stories)
        if mismatches and json.dumps(mismatches) != mine.get("priority_mismatches"):
            cmd_owner.note("groom", f"{name}: priority mismatch(es), no changes made: " + "; ".join(mismatches)[:600])
        mine["priority_mismatches"] = json.dumps(mismatches)
        names = name_drift.drift(root)  # a command, job label or file name matches its README heading (#840)
        if names and json.dumps(names) != mine.get("names"):
            cmd_owner.note("groom", f"{name}: " + name_drift.summary(names)[:700])
        mine["names"] = json.dumps(names)
        if synced := sync_blockers(slug, stories, run):  # each Blocked by line matches a dependency link, both ways (#1103)
            cmd_owner.note("groom", f"{name}: Blocked by lines and dependency links synced on " + ", ".join(f"#{n}" for n in synced))
        mine["impact"] = {str(n): v for n, v in impact(stories).items()}  # what each story unblocks and shares files with (#1090)
        if fixes:
            with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
                json.dump({"issues": fixes}, f)
                f.flush()
                batch_project.main(["--config", str(config), "--input", f.name])
            cmd_owner.note("groom", f"{name}: groom fixed {len(fixes)} card(s) that had drifted, were missing or lacked Priority, Size or Ready")
        for n, _, text in moved:  # a comment says why the epic moved, once its card has (#1105)
            run(["api", "-X", "POST", f"repos/{slug}/issues/{n}/comments", "-f", f"body={text}"])
        if moved:
            cmd_owner.note("groom", f"{name}: epic(s) moved with their stories: " + ", ".join(f"#{n} to {s}" for n, s, _ in moved))
        mine.update(ok=now, fp=fingerprint(slug, root, run), failed="")
        close_failure(slug)
        return True
    except (Exception, SystemExit) as exc:
        mine["failed"] = str(exc)[:200] or type(exc).__name__
        queue_failure(name, slug, config, mine["failed"])
        return False
    finally:
        with failure_log.locked(_state()):  # merge this board's record into the file as it is now, so another groom's record is kept
            latest = load_state()
            latest[slug] = mine
            failure_log.write_private(_state(), json.dumps(latest, indent=1))


def say(slug, number, text, run=gh):
    return run(["api", f"repos/{slug}/issues/{number}/comments", "-f", f"body={text}"]) is not None


def assign_epics(slug, stories, mine, epic_numbers=frozenset(), run=gh, config=""):
    """Sets the Epic line of each unlinked story that matches an open epic (#1099) and comments the epic, the match and the undo command.
    A story with no match gets one comment saying so. Epics are never assigned. An Epic line the owner removed from a story groom linked
    is remembered, so the story is not linked to that epic again. Returns (stories newly linked, themes for stories no epic holds)."""
    import board_grooming
    from lib import intake
    assigned, declined, none = mine.setdefault("epics", {}), mine.setdefault("epic_declined", {}), mine.setdefault("epic_none", [])
    for n, e in list(assigned.items()):
        if int(n) in stories and board_grooming.epic_of(stories[int(n)].get("body")) is None:
            assigned.pop(n)
            declined.setdefault(n, []).append(e)  # the Epic line is gone: the owner undid it
        elif int(n) not in stories:
            assigned.pop(n)  # the story is closed
    epics = {n: s for n, s in stories.items() if n in epic_numbers or board_grooming.is_epic(s)}
    free = {n: s for n, s in stories.items() if n not in epics and board_grooming.epic_of(s.get("body")) is None}
    linked, unmatched = [], {}
    for n, story in sorted(free.items()):
        hit = board_grooming.match_epic(story, epics, intake.files_area, declined.get(str(n), []))
        if hit is None:
            unmatched[n] = story
            if epics and n not in none and say(slug, n, "Groom found no epic that matches above the threshold, so this story keeps no Epic line.", run):
                none.append(n)
            continue
        epic, why = hit
        body = story.get("body") or ""
        body = (re.sub(r"^(Priority:)", f"Epic: #{epic}\n\\1", body, count=1, flags=re.M) if re.search(r"^Priority:", body, re.M)
                else body.rstrip("\n") + f"\nEpic: #{epic}\n")
        if run(["api", "-X", "PATCH", f"repos/{slug}/issues/{n}", "-f", f"body={body}"]) is None:
            continue
        story["body"] = body
        assigned[str(n)] = epic
        linked.append(n)
        say(slug, n, f"Groom set the Epic line to #{epic}: {why}. To undo: `olivercode board groom --undo {n} --config {config}`, or delete the Epic line.", run)
    return linked, board_grooming.themes(unmatched)


def undo_epic(slug, number, config, run=gh):
    """Removes the Epic line from the story and records the epic, so grooming links it there again only with a new reason (#1099)."""
    import board_grooming
    raw = run(["api", f"repos/{slug}/issues/{number}", "--jq", ".body"])
    if raw is None:
        raise RuntimeError(f"could not read #{number}")
    epic = board_grooming.epic_of(raw)
    if epic is None:
        return False
    if run(["api", "-X", "PATCH", f"repos/{slug}/issues/{number}", "-f", "body=" + board_grooming.EPIC_LINE.sub("", raw, count=1)]) is None:
        raise RuntimeError(f"could not edit #{number}")
    with failure_log.locked(_state()):
        latest = load_state()
        mine = latest.setdefault(slug, {})
        mine.setdefault("epic_declined", {}).setdefault(str(number), []).append(epic)
        mine.get("epics", {}).pop(str(number), None)
        failure_log.write_private(_state(), json.dumps(latest, indent=1))
    return True


def propose_epics(name, found, stories, slug):
    """One owner line for each theme of three or more unlinked stories, naming the stories in order. No epic is filed until the owner runs the line's command (#1099)."""
    import shlex
    for words, numbers in found:
        order = sorted(numbers, key=lambda n: (priority_of(stories[n]), n))
        refs = ", ".join(f"#{n}" for n in order)
        title = f"Epic: {' '.join(words)}"
        body = f"Work type: Epic\n\nStories in order: {refs}\n"
        command = f"olivercode story outbox add --repo {slug} --title {shlex.quote(title)} --body {shlex.quote(body)}"
        cmd_owner.add_once("groom", f"epic:{','.join(map(str, order))}",
                           f"{name}: approve a new epic on \"{' '.join(words)}\" holding {refs} in that order",
                           command=command, error="no open epic holds these stories; none is filed until you run this command")


RELATED = re.compile(r"^Related:.*$", re.M)
PATH_LIKE = re.compile(r"[/.]")


def related_to(body, stories):
    """Numbers of the open stories whose Files area shares a file or folder with this body's (#1004). No model call."""
    from lib import intake
    mine = intake.files_area(body)
    return sorted(n for n, s in stories.items() if intake.overlaps(mine, intake.files_area(s.get("body") or "")))


BLOCKED_BY = re.compile(r"^Blocked by:(.*)$", re.M | re.I)


def impact(stories):
    """{number: {"unblocks": open stories naming it in their Blocked by line, "shares": open stories sharing a file with it}} (#1090). No model call."""
    from lib import intake
    blockers = {n: {int(x) for line in BLOCKED_BY.findall(s.get("body") or "") for x in re.findall(r"#(\d+)", line)} for n, s in stories.items()}
    return {n: {"unblocks": sum(n in b for m, b in blockers.items() if m != n),
                "shares": related_to(s.get("body") or "", {m: t for m, t in stories.items() if m != n})}
            for n, s in sorted(stories.items())}


def named_blockers(body):
    """The story numbers a body's Blocked by lines name."""
    return {int(x) for line in BLOCKED_BY.findall(body or "") for x in re.findall(r"#(\d+)", line)}


def with_blocker(body, n):
    """The body with `Blocked by: #n` added to its Blocked by line, or as a new line when it has none."""
    body = body or ""
    if m := BLOCKED_BY.search(body):
        kept = re.findall(r"#\d+", m.group(1))
        line = "Blocked by: " + ", ".join(kept + [f"#{n}"]) + "."
        return body[:m.start()] + line + body[m.end():]
    return body.rstrip("\n") + f"\nBlocked by: #{n}.\n"


def sync_blockers(slug, stories, run=gh):
    """Make each story's Blocked by line and its GitHub dependency links agree, both ways (#1103). A named open blocker with no link gets the link and a
    comment, a link to an open story the body does not name adds the name to the body, and a link to a closed story is removed. Returns the numbers changed."""
    changed = []
    for n, story in sorted(stories.items()):
        named = named_blockers(story.get("body")) - {n}
        if not named and not (story.get("issue_dependencies_summary") or {}).get("total_blocked_by"):
            continue
        raw = run(["api", f"repos/{slug}/issues/{n}/dependencies/blocked_by"])
        try:
            rows = json.loads(raw) if raw is not None else None
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            continue
        linked = {r["number"]: r for r in rows if isinstance(r, dict) and "number" in r}
        for b, row in sorted(linked.items()):
            if row.get("state") != "open" and "id" in row:
                if run(["api", "-X", "DELETE", f"repos/{slug}/issues/{n}/dependencies/blocked_by/{row['id']}"]) is not None:
                    changed.append(n)
        for b in sorted(named - set(linked)):
            if b not in stories or "id" not in stories[b]:
                continue  # a closed or unread blocker needs no link
            if run(["api", "-X", "POST", f"repos/{slug}/issues/{n}/dependencies/blocked_by", "-F", f"issue_id={stories[b]['id']}"]) is not None:
                run(["api", "-X", "POST", f"repos/{slug}/issues/{n}/comments", "-f", f"body=Groom added the dependency link: blocked by #{b}, named in the Blocked by line."])
                changed.append(n)
        for b, row in sorted(linked.items()):
            if row.get("state") == "open" and b not in named:
                body = with_blocker(story.get("body"), b)
                if run(["api", "-X", "PATCH", f"repos/{slug}/issues/{n}", "-f", f"body={body}"]) is not None:
                    story["body"] = body
                    named.add(b)
                    changed.append(n)
    return sorted(set(changed))


def unblocks_of(slug, number):
    """The recorded count of stories this one unblocks, read from the groom record with no model call, 0 when none is recorded."""
    return int(((load_state().get(slug) or {}).get("impact") or {}).get(str(number), {}).get("unblocks", 0))


def tracked(root):
    """Every file and folder path on main, or None when git cannot read main."""
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
    from lib import intake
    made = {p.rstrip("/") for p in intake.creates(body)}
    return [p for p in intake.files_area(body) if PATH_LIKE.search(p) and p.rstrip("/") not in on_main and p.rstrip("/") not in made]


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
    """`olivercode board groom --fit BODY_FILE --title TITLE --config FILE` (#1004): rewrites BODY_FILE with its Related line and prints each
    missing path. It calls no model and returns 0 on a finding too, since the story still files."""
    opts = dict(zip(argv[::2], argv[1::2]))
    if len(argv) != 6 or set(opts) != {"--fit", "--title", "--config"}:
        print("Usage: olivercode board groom --fit BODY_FILE --title TITLE --config FILE")
        return 1
    config = Path(opts["--config"])
    cfg = json.loads(config.read_text(encoding="utf-8"))
    slug, root = f"{cfg['repoOwner']}/{cfg['repoName']}", config.resolve().parent.parent
    path = Path(opts["--fit"])
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


def command_undo(argv):
    """`olivercode board groom --undo N --config FILE` (#1099): removes the Epic line groom set on story N."""
    if len(argv) != 4 or argv[0] != "--undo" or argv[2] != "--config" or not argv[1].isdigit():
        print("Usage: olivercode board groom --undo N --config FILE")
        return 1
    cfg = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
    put_gh_on_path()
    done = undo_epic(f"{cfg['repoOwner']}/{cfg['repoName']}", int(argv[1]), argv[3])
    print(f"#{argv[1]} has no Epic line" if done else f"#{argv[1]} has no Epic line to remove")
    return 0


def command_groom(argv):
    if argv[:1] == ["--fit"]:
        return command_fit(argv)
    if argv[:1] == ["--undo"]:
        return command_undo(argv)
    force, args = "--force" in argv, [a for a in argv if a != "--force"]
    chosen = boards() if args == ["--all"] else [(Path(args[1]).parent.parent.name, Path(args[1]))] if len(args) == 2 and args[0] == "--config" else []
    if not chosen:
        print("Usage: olivercode board groom [--config FILE | --all | --force]")
        return 1
    code = 0 if all([groom_board(n, c, force) for n, c in chosen]) else 1
    return max(code, check_intake(chosen)) if args == ["--all"] else code


def check_intake(chosen, out=print) -> int:
    """The board sweep's second half (#982): the repeated-blocker check on the first board's repo and the intake check on every board. Returns 1 on a finding."""
    from lib import cmd_sweep, intake
    held = gh_budget.refusal() or gh_budget.points_refusal()
    if held:
        out("Intake check skipped: " + held.split(". ")[0])
        return 0
    fleet = cmd_sweep.repos(lambda: chosen)
    for line in intake.prevention(*fleet[0][1:]) if fleet else []:
        out(line)
    return intake.run(fleet)
