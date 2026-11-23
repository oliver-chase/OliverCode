"""The weekly retro: every lesson with no check becomes one story request, and the structure metrics print.

`olivercode retro` prints the requests and files nothing. `--file` appends each request to the local candidates list
(candidates.py, #895) and marks the lesson covered by it, so the next retro adds nothing twice. Nothing reaches the board
until the owner runs `olivercode candidates promote`. The retro date lives in ~/.olivercode/retro.json (OLIVERCODE_HOME overrides the folder). Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from lib import candidates, failure_log, gh_budget, launchd, lesson_cover, lessons
from lib.local_config import OC_ROOT, setting
from lib.repo_profiles import iter_fleet, load_repo_profiles

STALE_DAYS = 8
WINDOW_DAYS = 7
USAGE = "Usage: olivercode retro [--file] [--root DIR] | --auto | --schedule | --unschedule"


def epic_line() -> str:
    """The `Epic: #N` line for a filed story, from `retroEpic` in olivercode.local.json (a number, "#N" or "owner/repo#N"),
    or "" when none is configured, so a user with no such epic gets no Epic line (#691)."""
    value = str(setting("retroEpic") or "").strip()
    found = re.fullmatch(r"((?:[\w.-]+/[\w.-]+)?#)?(\d+)", value)
    return f"Epic: {found.group(1) or '#'}{found.group(2)}\n" if found else ""


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _sentence(value: str) -> str:
    return _text(value).rstrip(".")


def slug(repo: Path) -> str:
    """owner/name from the repo's origin remote, or "" when it has none."""
    ran = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    found = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", ran.stdout.strip() + " ")
    return found.group(1) if found else ""


def sources(fleet_root: Path | None = None, oc_root: Path | None = None) -> list[tuple[str, Path | None]]:
    """(label, repo) for each log the retro reads: OliverCode itself, every fleet repo, then the structure log (repo None)."""
    # Resolved per call: a default bound at import would ignore a patched OC_ROOT and read the real checkout.
    oc_root = Path(oc_root or OC_ROOT)
    try:
        profiles = load_repo_profiles(oc_root)[0]
    except (OSError, ValueError):
        profiles = {}
    found = [(name, path) for name, _p, path in iter_fleet(profiles, fleet_root or oc_root.parent)]
    own = [] if any(Path(p).resolve() == Path(oc_root).resolve() for _n, p in found) else [(Path(oc_root).name, Path(oc_root))]
    return own + found + [("structure", None)]


def build(lesson: dict, repo_slug: str, label: str) -> dict:
    """One story request for one lesson, in the format of skills/backlog/references/story-template.md."""
    what, why, rule = _sentence(lesson["what"]), _sentence(lesson["why"]), _sentence(lesson["rule"])
    body = (f'**As the owner**, I want a check that holds the rule "{rule}", so that the problem "{what}" does not '
            "happen again.\n\n```gherkin\n"
            f"Feature: {rule}\n  Scenario: The lesson {lesson['id']} holds\n"
            f"    Given {what}\n    When the check runs\n    Then the rule holds: {rule}\n```\n\n"
            f"{epic_line()}Priority: P1. Size: S. Work type: Story.\n\n"
            "Existing coverage checked: the lesson register holds this lesson uncovered, and the filing run found no open story for it.\n\n"
            f"Lesson {lesson['id']} ({label}, {lesson.get('date', '?')}). Why it happened: {why}.\n")
    return {"lesson": lesson["id"], "label": label, "repo": repo_slug, "title": f"Check for lesson {lesson['id']}: {rule}"[:110],
            "body": body, "log": None}


def requests(fleet_root: Path | None = None, oc_root: Path | None = None) -> list[dict]:
    """A story request for every uncovered lesson. Each carries `log`, the repo the lesson lives in (None for structure)."""
    oc_root = Path(oc_root or OC_ROOT)
    out, by_rule = [], {}
    for label, repo in sources(fleet_root, oc_root):
        target = slug(oc_root) if repo is None else slug(repo)
        log = None if repo is None else str(repo)
        for lesson in lessons.uncovered(repo):
            key = lesson_cover.rule_key(lesson["rule"])
            if key in by_rule:  # the same rule is one story, and every lesson that states it is covered by it
                by_rule[key]["covers"].append((lesson["id"], log))
                continue
            req = build(lesson, target, label)
            req["log"] = log
            req["covers"] = [(lesson["id"], log)]
            by_rule[key] = req
            out.append(req)
    return out


def uncovered_count(fleet_root: Path | None = None, oc_root: Path | None = None) -> int:
    return sum(len(lessons.uncovered(repo)) for _label, repo in sources(fleet_root, oc_root))


def _retro_file() -> Path:
    return failure_log.home() / "retro.json"


def last_retro() -> date | None:
    try:
        return date.fromisoformat(json.loads(_retro_file().read_text(encoding="utf-8"))["last"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_retro(today: date | None = None) -> None:
    target = _retro_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"last": (today or date.today()).isoformat()}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def staleness(today: date | None = None) -> str:
    """Why the retro is overdue, or "" when one ran within the last eight days."""
    last = last_retro()
    if last is None:
        return "no retro has run on this machine. Run `olivercode retro`, and `olivercode retro --file` to file its stories"
    age = ((today or date.today()) - last).days
    if age > STALE_DAYS:
        return f"the last retro ran {age} days ago. Run `olivercode retro --file`"
    return ""


def run_gh(args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def file_requests(reqs: list[dict], runner=None) -> list[dict]:
    """Append each request to the candidates list and cover its lessons, so the next retro adds none of them again (#895).

    Nothing is created on GitHub, so no budget check applies and nothing is left pending."""
    for req in reqs:
        if not req["repo"]:
            continue
        candidates.add("retro", req["repo"], req["title"], req["body"])
        for lesson_id, log in req.get("covers") or [(req["lesson"], req["log"])]:
            lessons.cover(lesson_id, "candidates", log)
    return [r for r in reqs if r["repo"]]


def auto_cover_on() -> bool:
    """True when this machine's olivercode.local.json sets "autoCoverLessons": true. Off by default, so a fork opts in."""
    try:
        return setting("autoCoverLessons") is True
    except (OSError, ValueError, RuntimeError):
        return False


def open_story_count(repo_slug: str) -> int | None:
    """The open stories (not pull requests) in a repo, or None when gh could not read them."""
    ran = run_gh(["api", f"repos/{repo_slug}/issues?state=open&per_page=100", "--paginate", "--jq", '.[] | select(has("pull_request") | not) | .number'])
    return len((ran.stdout or "").split()) if ran.returncode == 0 else None


def auto_prevention(out=print, fetch=None) -> None:
    """Add a candidate for each blocker the failure log holds 3 or more times, at most `retroFilesPerRun` (#971). Creates no issue."""
    from lib import intake
    repo = slug(OC_ROOT)
    if not repo or not lesson_cover.own_backlog(repo):
        return
    epic = re.search(r"(\d+)\s*$", epic_line())
    for line in intake.prevention(repo, int(epic.group(1)) if epic else 1, **({"fetch": fetch} if fetch else {})):
        out(line)


def auto_cover(runner=run_gh, out=print, fetch=None) -> int:
    """Add a candidate for each uncovered lesson and each repeated blocker, with no model call and no output when nothing waits (#659).

    One run adds at most `retroFilesPerRun` of each, none for a lesson that names a story an auto filer made, none in a repo over `openStoryCap` (#875).
    Nothing here creates an issue (#971): the owner promotes a candidate with `olivercode candidates promote`."""
    if not auto_cover_on():
        return 0
    auto_prevention(out, fetch)
    if not uncovered_count():
        return 0
    lim = candidates.limits()
    refs = {str(r["covered_by"]) for _label, repo in sources() for r in lessons.read(repo) if str(r.get("covered_by") or "").startswith("#")}
    reqs = [r for r in requests() if not any(re.search(re.escape(ref) + r"\b", r["title"] + r["body"]) for ref in refs)]
    if lesson_cover.own_backlog(slug(OC_ROOT)):
        counts = {r["repo"]: open_story_count(r["repo"]) if r["repo"] else 0 for r in reqs}
        reqs = [r for r in reqs if counts[r["repo"]] is not None and counts[r["repo"]] <= lim["openStoryCap"]][:int(lim["retroFilesPerRun"])]
    if not reqs:
        return 0
    if not lesson_cover.own_backlog(slug(OC_ROOT)):  # no backlog of this checkout's own: nothing is filed upstream
        for req in reqs:
            ref = lesson_cover.write_request(req)
            for lesson_id, log in req["covers"]:
                lessons.cover(lesson_id, ref, log)
            out(f"Wrote a story request to {ref} for lesson {req['lesson']}")
        return 0
    for req in file_requests(reqs):
        out(f"Added a candidate for lesson {req['lesson']}. Run `olivercode candidates` to review it")
    record_retro()
    return 0


def schedule(on: bool) -> int:
    return launchd.schedule(on, "com.olivercode.lessons", lambda: launchd.job("com.olivercode.lessons", ["retro", "--auto"], "lessons.out", StartInterval=3600), "lesson job",
                            "`olivercode retro --auto` runs hourly and adds a candidate for each lesson with no check, at most a few per run. Remove it with `olivercode retro --unschedule`.")


def command_retro(argv: list[str], runner=run_gh, now: datetime | None = None, reader=run_gh, fetch=None) -> int:
    from lib.cli import take_root_flag
    if argv == ["--auto"]:
        return auto_cover(runner, fetch=fetch)
    if argv in (["--schedule"], ["--unschedule"]):
        return schedule(argv == ["--schedule"])
    do_file = "--file" in argv
    root, rest = take_root_flag([a for a in argv if a != "--file"])
    if rest:
        print(USAGE)
        return 1
    reqs = requests(root)
    if not reqs:
        print("Every lesson has a check or a story.")
    elif not do_file:
        print(f"{len(reqs)} lesson(s) have no check. Nothing is filed without --file.\n")
        for req in reqs:
            print(f"--- {req['repo'] or req['label']}: {req['title']}\n{req['body']}")
    else:
        for req in file_requests(reqs):
            print(f"Added a candidate in {req['repo']} for lesson {req['lesson']}. Run `olivercode candidates` to review it")
    if do_file:
        record_retro()
    return 0
