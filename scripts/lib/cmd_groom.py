"""Launcher command `board groom`: fixes drifted and missing board cards (#660) and fills the rest of the grooming (#724).
`olivercode board groom [--config FILE | --all | --force]` calls no model; a repo unchanged since the last run costs no GraphQL call.

Beyond drift it sets a blank Priority and Size from the story body, moves an unblocked Backlog story that has both to
Ready, and queues one owner line for each pair of open stories that look like duplicates. It also does the work of the retired board sweep: it reads each board for drift, runs the intake check and files the repeated-blocker story (#982). `maintain --fix` runs it, the
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


SECURITY = re.compile(r"secret|credential|leak|vulnerab|security|data loss|lose data|lost data", re.I)
DEFECT = re.compile(r"\b(bug|broken|fails?|failing|crash|regress\w*|wrong)\b", re.I)
BLOCKED = re.compile(r"blocked by|depends on #|needs a decision|waiting on", re.I)
HELD_LABELS = {"owner-action", "blocked"}
SIZES = ((500, "XS"), (1000, "S"), (2000, "M"), (4000, "L"))
FRESH_HOURS, STALE_HOURS = 24, 48


def open_stories(slug, run=gh):
    """{number: {title, body, labels}} of the repo's open issues."""
    raw = run(["api", f"repos/{slug}/issues?state=open&per_page=100", "--paginate", "--jq",
               '.[] | select(has("pull_request") | not) | {number, title, body, labels: [.labels[].name]}'])
    if raw is None:
        raise RuntimeError(f"could not read the open issues of {slug}")
    return {o["number"]: o for o in (json.loads(l) for l in raw.splitlines() if l.strip())}


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


def filled(items, stories, fixes, hold=frozenset()):
    """Merge into `fixes` a Priority and Size for each open story that lacks one and a move to Ready for each unblocked Backlog story that `hold` does not name,
    so a flagged story waits in Backlog for the owner (#1014)."""
    import board_grooming
    by = {f["number"]: f for f in fixes}
    carded = {(i.get("content") or {}).get("number"): i for i in items}
    for number, story in sorted(stories.items()):
        card = carded.get(number, {})
        want = {}
        if not card.get("priority"):
            want["priority"] = priority_of(story)
        if not card.get("size"):
            want["size"] = size_of(story)
        status = by.get(number, {}).get("fields", {}).get("status") or card.get("status") or "Backlog"
        epic = str(board_grooming.field(card, "work type") or "").lower() == "epic"
        held = HELD_LABELS & set(story.get("labels") or []) or BLOCKED.search(story.get("body") or "")
        if status == "Backlog" and not epic and not held and number not in hold:
            want["status"] = "Ready"
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


def duplicates(items):
    import board_grooming
    return board_grooming.overlapping_titles(items, {"Backlog", "Ready", "In Progress"})


def pair_numbers(pairs):
    """The story numbers named in each duplicate line, so both stories of a pair stay in Backlog (#1014)."""
    return {int(n) for pair in pairs for n in re.match(r"#(\d+) and #(\d+) share", pair).groups()}


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


def groom_board(name: str, config: Path, force=False, now=None, run=gh):
    import batch_project
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
        stories = open_stories(slug, run)
        from lib import intake
        found = intake.plan(list(stories.values()))
        flagged = [f"#{n} names no files area, rewrite it" for n in found["rewrite"]] + [f"#{n} {why}" for n, why in found["waits"].items()]
        pairs = duplicates(items)
        hold = set(found["rewrite"]) | set(found["waits"]) | pair_numbers(pairs)  # flagged stories stay in Backlog until the owner acts (#1014)
        fixes = filled(items, stories, [{"number": n, "fields": {"status": "Complete" if k == "close" else "Backlog"}}
                                for n, k in check_board_hygiene.status_drift(items, states, slug)], hold)
        if line := review_imported(slug, stories, mine, int(cfg.get("epic") or 1), run, queued=_queued):
            cmd_owner.note("groom", f"{name}: {line}")
        if flagged and json.dumps(flagged) != mine.get("split"):
            cmd_owner.note("groom", f"{name}: {len(flagged)} story(ies) need a rewrite before dispatch: " + "; ".join(flagged)[:600])
        mine["split"] = json.dumps(flagged)
        if pairs and json.dumps(pairs) != mine.get("dups"):
            cmd_owner.note("groom", f"{name}: {len(pairs)} possible duplicate pair(s): " + "; ".join(pairs)[:600])
        mine["dups"] = json.dumps(pairs)
        renames = [f"#{n} {why}" for n, why in rename_check.missing_line(stories).items()]  # a rename story names its old name (#838)
        if renames and json.dumps(renames) != mine.get("renames"):
            cmd_owner.note("groom", f"{name}: {len(renames)} rename story(ies) name no old name: " + "; ".join(renames)[:600])
        mine["renames"] = json.dumps(renames)
        names = name_drift.drift(root)  # a command, job label or file name matches its README heading (#840)
        if names and json.dumps(names) != mine.get("names"):
            cmd_owner.note("groom", f"{name}: " + name_drift.summary(names)[:700])
        mine["names"] = json.dumps(names)
        if fixes:
            with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
                json.dump({"issues": fixes}, f)
                f.flush()
                batch_project.main(["--config", str(config), "--input", f.name])
            cmd_owner.note("groom", f"{name}: groom fixed {len(fixes)} card(s) that had drifted, were missing or lacked Priority, Size or Ready")
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


RELATED = re.compile(r"^Related:.*$", re.M)
PATH_LIKE = re.compile(r"[/.]")


def related_to(body, stories):
    """Numbers of the open stories whose Files area shares a file or folder with this body's (#1004). No model call."""
    from lib import intake
    mine = intake.files_area(body)
    return sorted(n for n, s in stories.items() if intake.overlaps(mine, intake.files_area(s.get("body") or "")))


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


def command_groom(argv):
    if argv[:1] == ["--fit"]:
        return command_fit(argv)
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
