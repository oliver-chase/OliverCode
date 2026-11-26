"""Launcher command `board groom`: reads each board and reports what it found. It writes nothing to GitHub (#1275).

`olivercode board groom [--config FILE | --all | --force]` calls no model; a repo unchanged since the last run costs no GraphQL call.
It reports drifted and missing cards, a blank Priority or Size, stories that name no files area, possible duplicate pairs, rename
stories with no old name, name drift, imported priorities nobody reviewed, the intake check and the repeated gate failures.
It changes no issue body, label, link, project status or field and no open or closed state, and it creates no issue or label.
The findings go to the owner queue and to the groom state file in ~/.olivercode. `maintain --fix` runs it, the SessionStart hook
starts it in the background when the last success is over 24 hours old, and `health` fails after 48.
"""

import hashlib
import json
import re
import subprocess
import sys
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


def gh(args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
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
    """Merge into `fixes` a Priority and Size for each open story that lacks one and a move to Ready for each unblocked Backlog story that `hold` does not name.
    The result is a report of what is missing and is never written to the board (#1275)."""
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
REVIEWED = "priority-reviewed"
def imported(stories):
    """Numbers of open stories whose Priority was copied from a file and has not been reviewed since."""
    return sorted(n for n, s in stories.items() if IMPORTED.search(s.get("body") or "") and STATED.search(s.get("body") or "")
                  and REVIEWED not in (s.get("labels") or []))


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


def groom_board(name: str, config: Path, force=False, now=None, run=gh):
    import board_rest
    import check_board_hygiene
    now = time.time() if now is None else now
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
            mine["ok"] = now
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
        todo = imported(stories)
        if todo and json.dumps(todo) != mine.get("imported"):
            cmd_owner.note("groom", f"{name}: {len(todo)} imported priorities have not been judged against the code: " + ", ".join(f"#{n}" for n in todo)[:400])
        mine["imported"] = json.dumps(todo)
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
        if fixes and json.dumps(fixes) != mine.get("cards"):
            cmd_owner.note("groom", f"{name}: {len(fixes)} card(s) have drifted, are missing or lack Priority, Size or Ready: " + ", ".join(f"#{f['number']}" for f in fixes)[:400])
        mine["cards"] = json.dumps(fixes)
        mine.update(ok=now, fp=fingerprint(slug, root, run), failed="")
        return True
    except (Exception, SystemExit) as exc:
        mine["failed"] = str(exc)[:200]
        cmd_owner.note("groom", f"{name}: grooming failed: {mine['failed']}")
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
    """The board sweep's second half (#982): the repeated-blocker report and the intake check on every board. Both only report. Returns 1 on a finding."""
    from lib import cmd_sweep, intake
    held = gh_budget.refusal() or gh_budget.points_refusal()
    if held:
        out("Intake check skipped: " + held.split(". ")[0])
        return 0
    fleet = cmd_sweep.repos(lambda: chosen)
    for line in intake.repeated_blockers():
        out(line)
    return intake.run(fleet)
