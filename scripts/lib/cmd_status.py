"""Launcher command `status`: the open story count, the landing rate, the tokens per closed story and the projected zero date for this repo, from gh REST only, with no model call.

`olivercode status [--root DIR]` reads the repo's open count and the stories opened and closed in the last seven days. A falling count prints the stories
landed per day and the date the count reaches zero at that pace. A flat or rising count prints the same figures and says the date is not reachable.

`olivercode status digest [--root DIR]` writes the same board figures with the open stories in priority order, the last five landed, what waits on the owner,
the latest decisions and the run-log rows to `status-digest.md` in the OliverCode home, at most DIGEST_TOKENS tokens. A new owner thread starts from that file
alone (#892). The session-start hook refreshes it once it is older than DIGEST_TTL and prints one line with the open count (#985, #1017). It calls no model.

`olivercode status page` rewrites the local status page from the last run state with no model call, and `olivercode status publish [--probe]` publishes that
page to the City artifact URL on the smallest model and prints whether the Artifact tool worked headless, with the tokens and cost of the call (#990).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import candidates, cmd_groom, cmd_owner, failure_log, gh_budget, open_issues, relay, repo_state, run_lock, status_page, validate_queue, status_report
from lib import briefing, local_config
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import issue_count  # noqa: E402
import log_action  # noqa: E402

DAYS = 7
STALL_MINUTES = run_lock.STALL_MINUTES  # a building story whose progress has not moved for this long is reported as stalled (#987, #1020)
CLEAN_STOPS = ("", "end_turn", "completed")  # the stop reasons that end a round without trouble
QUIET_MINUTES = 20  # a building story whose log and commits have not moved for this long says so on its line (#1086)
DIGEST_TOKENS = 1500
DIGEST_TTL = 600  # seconds a written digest serves a new session, so a session that starts soon after another makes no GitHub call (#1017)
BOARD_RE = re.compile(r"^Board: (\S+): (\d+) open\.", re.MULTILINE)  # the repo and open count the digest's board line states
DIGEST_CHARS = 3  # characters per token in the estimate: English runs near four, and ids, paths and code run shorter, so three keeps the digest under the limit
OPEN_SHOWN = 10  # the open stories the digest lists, highest priority first
DIGEST_ITEMS = 5  # the latest decisions and the latest run-log rows the digest keeps before it trims to the limit
OWNER_GATED = " (owner gated)"  # the digest's mark on a story that waits on the owner, so Next Ready skips it (#1020)
USAGE = "Usage: olivercode status [--root DIR] | olivercode status digest [--root DIR] | olivercode status page | olivercode status publish [--probe]"


def recent(slug: str, since: datetime, runner=issue_count.gh_list) -> list[dict] | None:
    """Issues (not pull requests) updated since `since`, or None when the read fails. Any issue closed or opened in the window was updated in it."""
    done = runner(["-X", "GET", f"repos/{slug}/issues", "-f", "state=all", "-f", f"since={since:%Y-%m-%dT%H:%M:%SZ}", "-f", "per_page=100", "--paginate", "--slurp"])
    if done.returncode != 0:
        return None
    try:
        pages = json.loads(done.stdout or "[]")
    except ValueError:
        return None
    rows = [row for page in pages for row in (page if isinstance(page, list) else [page])]
    return [row for row in rows if isinstance(row, dict) and "pull_request" not in row]


def _after(stamp: str | None, since: datetime) -> bool:
    return bool(stamp) and datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= since


def summary(open_now: int, rows: list[dict], now: datetime, days: int = DAYS) -> str:
    """The status lines for an open count and the issues updated in the last `days`."""
    since = now - timedelta(days=days)
    opened = sum(1 for r in rows if _after(r.get("created_at"), since))
    closed = sum(1 for r in rows if _after(r.get("closed_at"), since))
    rate = closed / days
    head = f"{open_now} open. In the last {days} days {closed} closed and {opened} opened, so {rate:.1f} stories landed per day."
    if open_now == 0:
        return head + " The backlog is at zero."
    if closed <= opened:
        return head + " The count is flat or rising, so the projected zero date is not reachable at this rate."
    net = (closed - opened) / days
    zero = (now + timedelta(days=open_now / net)).date()
    return head + f" The count falls {net:.1f} per day, so it reaches zero on {zero:%Y-%m-%d}."


def claims_path() -> Path:
    return gh_budget.home() / "dispatch-claims.json"


def live_claims(now: float) -> dict:
    """The dispatch claims younger than the claim window, by story key 'owner/repo#N', each with its agent and its time."""
    try:
        held = json.loads(claims_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    limit = log_action.CLAIM_HOURS * 3600
    return {key: mine for key, mine in held.items() if isinstance(mine, dict) and now - float(mine.get("at", 0)) < limit}


def in_progress(now: float) -> set[str]:
    """The 'owner/repo#N' keys of stories In Progress on a board copy under ten minutes old. It reads the shared local copy and fetches nothing (#1188)."""
    from lib import board_mirror
    found = set()
    for path in gh_budget.home().glob("board-*.json"):
        try:
            if now - path.stat().st_mtime >= board_mirror.FRESH_SECONDS:
                continue
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in items if isinstance(items, list) else []:
            content = (item or {}).get("content") or {}
            if item.get("status") == "In Progress" and content.get("number") and content.get("repository"):
                found.add(f"{content['repository']}#{content['number']}")
    return found


def github_claims(keys, runner=None) -> dict[str, tuple[str, str]]:
    """{story key: (session, time)} for each story whose GitHub claim comment is live, one REST read per key (#1188). An unreadable story is left out."""
    runner = runner or log_action.gh_api
    held = {}
    for key in sorted(keys):
        repo, _, n = key.rpartition("#")
        try:
            said = log_action.claim_status(repo, int(n), runner)
        except (RuntimeError, ValueError, OSError):
            continue
        if match := re.match(r"claimed by (.+) at (\S+)$", said):
            held[key] = (match.group(1), match.group(2))
    return held


def claim_lines(now: float, local: dict, remote: dict) -> list[str]:
    """One line for each live claim, local or on GitHub: the story, who holds it and for how long. A story the runner holds in the local file and a different session
    holds on GitHub is flagged as a possible duplicate (#1188)."""
    lines = []
    for key in sorted(set(local) | set(remote)):
        repo, _, n = key.rpartition("#")
        mine, theirs = local.get(key), remote.get(key)
        if mine:
            began, holder = float(mine.get("since") or mine.get("at", 0)), str(mine.get("agent") or "unnamed")
        else:
            stamp = log_action._parse_time(theirs[1])
            began, holder = (stamp.timestamp() if stamp else now), theirs[0]
        line = f"{repo.rsplit('/', 1)[-1]} #{n} · held by {holder} · {max(0, int((now - began) // 60))}m"
        if mine and theirs and theirs[0] != holder:
            line += f" · possible duplicate: {theirs[0]} also holds it on GitHub"
        lines.append(line)
    return lines


def estimate_line(slug: str, now: float) -> str:
    """The estimated finish of the run in progress, or the reason there is none yet, read from the run state the status page uses. '' when no run is active (#1189)."""
    entry = status_report.load_state().get(slug)
    if not isinstance(entry, dict) or not entry.get("active"):
        return ""
    if not entry.get("estimate_min"):
        return f"Estimate: none yet, because no story landed in the last {DAYS} days to time."
    end = float(entry["started"]) + entry["estimate_min"] * 60
    left = int((end - now) // 60)
    if left <= 0:
        return f"Estimate: the run is past its estimate of {datetime.fromtimestamp(end):%H:%M}."
    return f"Estimate: finishing near {datetime.fromtimestamp(end):%H:%M}, {left} minutes left."


def landed_today_lines(slug: str, now: float, log: list[dict]) -> list[str]:
    """What landed today with each story's tokens and cost from the run log, newest first, at most five lines of stories (#1189)."""
    today = datetime.fromtimestamp(now).date()
    rows = [r for r in status_report.history(log, slug, now, days=2) if datetime.fromtimestamp(status_report._epoch(r.get("at"))).date() == today]
    if not rows:
        return []
    priced = [r["cost"] for r in rows if r["cost"] is not None]
    lines = [f"Landed today: {len(rows)} {'story' if len(rows) == 1 else 'stories'}, {sum(r['tokens'] for r in rows):,} tokens, {status_report._money(sum(priced) if priced else None)}."]
    for r in rows[:5]:
        lines.append(f"  #{str(r['story']).rsplit('-', 1)[-1]} {_text(r.get('title'), 50)} · {r.get('model') or 'unknown'} · {r['tokens']:,} tokens · {status_report._money(r['cost'])}")
    return lines + ([f"  and {len(rows) - 5} more."] if len(rows) > 5 else [])


def runner_alive() -> bool:
    """True when a drain or dispatch process runs on this machine, read from the process table. No model call (#987)."""
    try:
        return subprocess.run(["pgrep", "-f", "olivercode (drain|dispatch)"], capture_output=True).returncode == 0
    except OSError:
        return False


def held_numbers(now: float, slug: str = "") -> set[int]:
    """The story numbers that a live claim or an open owner-queue step holds back from Ready. A claim names its story in its key, and a policy stop names
    its story in its step (#1058). With `slug`, only that repo's claims count, since another repo's story with the same number holds nothing here (#1095)."""
    held = {int(key.rsplit("#", 1)[-1]) for key in live_claims(now) if key.rsplit("#", 1)[-1].isdigit() and (not slug or key.rpartition("#")[0] == slug)}
    try:
        steps = [i for i in cmd_owner.items() if i["status"] == "open"]
    except (OSError, ValueError, KeyError):
        steps = []
    return held | {int(n) for i in steps for n in re.findall(r"Story #(\d+)", str(i.get("step", "")))}


def closed_claims(claims: dict, slug: str, rows: list[dict], runner=issue_count.gh_list) -> set[str]:
    """The claim keys whose story is closed. This repo's come from ROWS, the issues updated in the last week, and another repo's from one REST read each (#1095)."""
    done = set()
    for key in claims:
        repo, _, n = key.rpartition("#")
        if not n.isdigit():
            continue
        if repo == slug:
            if any(r.get("number") == int(n) and r.get("state") == "closed" for r in rows):
                done.add(key)
            continue
        try:
            read = runner([f"repos/{repo}/issues/{n}", "--jq", ".state"])
        except (OSError, subprocess.SubprocessError):
            continue  # an unreadable repo leaves its claim shown as building
        if read.returncode == 0 and read.stdout.strip() == "closed":
            done.add(key)
    return done


def _number(line: str) -> int | None:
    """The issue number a digest story line names, or None when the line names none."""
    found = re.search(r"#(\d+)", line)
    return int(found.group(1)) if found else None


def next_ready(path: Path, held: set[int] = frozenset()) -> str:
    """The first open story in the status digest that is neither in HELD nor owner-gated, which is the next Ready story in priority order, or '' when
    none is or no digest is written (#1020). The digest lists only its first OPEN_SHOWN open stories."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parts = text.split("\n## Open,", 1)
    if len(parts) < 2:
        return ""
    for line in parts[1].splitlines()[1:]:
        if line.startswith("## "):
            break
        if line.startswith("- ") and not line.endswith(OWNER_GATED) and _number(line) not in held:
            return line[2:]
    return ""


def stall_line(n: str, mine: dict, minutes: int, holder: dict | None) -> str:
    """The warning for a claim with no progress for STALL_MINUTES. While a run holds the repo, the warning names that run's process and the kill that
    stops it, which releases the claim (#1076). Dispatch would only join that run's queue, so it is named only when no run holds the repo."""
    if not holder:
        return f"Warning: the runner has stalled on #{n}. Nothing has moved for {minutes} minutes. Resume it with `olivercode dispatch {n}`."
    pid = holder.get("pid")
    return (f"Warning: #{n} holds a claim by {mine.get('agent')} with no progress for {minutes} minutes, while process {pid} holds the repo. "
            f"Stop that run with `kill {pid}`: its SIGTERM releases the claim and the run lock, and the story goes back to Ready. Then `olivercode drain REPO` builds it again.")


def _stamp(row: dict, default: float) -> float:
    """The time a run-log row was written, or DEFAULT when it has no readable time."""
    try:
        return datetime.fromisoformat(str(row["at"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return default


def this_run(rows: list[dict], began: float) -> list[dict]:
    """The rows logged since the claim began, which are this run's. A row with no readable time counts as this run's (#1086)."""
    return [r for r in rows if _stamp(r, began) >= began]


def round_count(rows: list[dict]) -> int:
    """The number of distinct round entries logged for a story, representing builder invocations (#1122)."""
    return len([r for r in rows if isinstance(r.get("round"), int)])


def turn_limit_hits(rows: list[dict]) -> int:
    """The number of times a story stopped on the turn limit, counting restarts (#1122)."""
    return sum(1 for r in rows if r.get("stop") == "turn_limit")










def _did(row: dict) -> str:
    """What a run-log row says the story did, in a few words."""
    if "review" in row:
        return f"the fresh reader's {row['review']}"
    if not isinstance(row.get("round"), int):
        return "writing a run-log row"
    return f"ending round {row['round']}" + (f" with {row['stop']}" if row.get("stop", "") not in CLEAN_STOPS else "")


def quiet_note(rows: list[dict], began: float, now: float, committed: float | None) -> str:
    """'Warning: No progress for M minutes: ...' when neither this run's log nor its worktree's commits have moved for QUIET_MINUTES, else '' (#1086)."""
    moves = [(_stamp(r, began), _did(r)) for r in this_run(rows, began)] + ([(committed, "a commit")] if committed and committed >= began else [])
    at, what = max(moves, key=lambda m: m[0], default=(began, "starting the builder session"))
    quiet = int((now - at) // 60)
    return f"Warning: No progress for {quiet} minutes: the last thing it did was {what} at {datetime.fromtimestamp(at):%H:%M}." if quiet >= QUIET_MINUTES else ""


def turn_limit_warning(n: str, hits: int) -> str:
    """A warning when a story has hit the turn limit multiple times, so it keeps restarting (#1122)."""
    plural = "s" if hits != 1 else ""
    return f"Warning: #{n} has hit the turn limit {hits} time{plural}. The claim keeps restarting. Delete its entry in {claims_path()} to release it."


def story_notes(now: float, claims: dict, log: list[dict], alive: bool, holder: dict | None, commits: dict[str, float] | None) -> dict[str, str]:
    """The warning under each building story, by story number: a claim with no live runner, a claim with no progress for STALL_MINUTES (#987, #1020), a claim
    whose round hit the turn limit twice (#1122), or a claim whose log and worktree commits have not moved for QUIET_MINUTES (#1086). `holder` is the live run that holds the repo, if any (#1076)."""
    notes = {}
    for key, mine in sorted(claims.items()):
        n = key.rsplit("#", 1)[-1]
        progress = float(mine.get("at", 0))
        if holder and n.isdigit() and int(n) in (holder.get("building") or []):
            progress = max(progress, float(holder.get("beat", 0)))  # the live runner beats while it builds the story (#1020)
        story_log = [r for r in log if r.get("story") == f"story-{n}"]
        if not alive:
            notes[n] = (f"Warning: #{n} holds a claim by {mine.get('agent')} but no drain or dispatch process is running. The claim expires by itself "
                        f"after {log_action.CLAIM_HOURS} hours, or delete its entry in {claims_path()} to release it now.")
        elif (now - progress) / 60 > STALL_MINUTES:
            notes[n] = stall_line(n, mine, int((now - progress) // 60), holder)
        elif (hits := turn_limit_hits(story_log)) >= 2:
            notes[n] = turn_limit_warning(n, hits)
        elif story_log and story_log[-1].get("stop") == "api_error":
            notes[n] = f"Warning: the last Claude API call failed: {str(story_log[-1].get('stderr_tail') or 'cause not recorded')[:180]}"
        elif quiet := quiet_note(story_log, float(mine.get("since") or mine.get("at", 0)), now, (commits or {}).get(n)):
            notes[n] = quiet
    return notes

def idle_line(alive: bool, open_now: int) -> str:
    """The line the Building section prints when no story is building (#987)."""
    if alive:
        return "The runner is running and no story is building."
    return f"Runner idle: no story is building and {open_now} stories are open. Start it with `olivercode drain REPO`."

def last_lines(alive: bool, landed_row: dict | None, ready: str, log: list[dict], holder: dict | None) -> list[str]:
    """The Last landed section: the newest landing, the next Ready story, then an indented warning when the last run did not stop cleanly (#987).
    City's own publish rounds (#990) are not a story's run, so they are skipped when finding that last run."""
    lines = [f"Last landed: #{landed_row.get('number')} {_text(landed_row.get('title'), 60)}." if landed_row else f"Last landed: none in the last {DAYS} days."]
    if ready:
        lines.append(f"Next Ready: {ready}.")
    runs = [r for r in log if r.get("story") != "city-publish"]
    if runs and runs[-1].get("stop", "") not in CLEAN_STOPS:
        story = str(runs[-1].get("story", ""))
        resume = "" if holder else f" Resume it with `olivercode dispatch {story.rsplit('-', 1)[-1]}`."
        cause = f": {str(runs[-1].get('stderr_tail'))[:180]}" if runs[-1].get("stop") == "api_error" and runs[-1].get("stderr_tail") else ""
        lines.append(f"  Warning: the last run on {story} stopped with {runs[-1].get('stop')}{cause}.{resume}")
    return lines



def tokens_per_closed(rows: list[dict], log: list[dict]) -> tuple[int, int, float | None] | None:
    """Average all-token usage and cost per recently closed story, including review/fix sessions (#1152)."""
    spent: dict[str, int] = {}
    costs: dict[str, float] = {}
    cost_seen: set[str] = set()
    for entry in log:
        match = re.fullmatch(r"(story-\d+)(?:-(?:review|fix))?", str(entry.get("story") or ""))
        if not match:
            continue
        key = match.group(1)
        spent[key] = spent.get(key, 0) + sum(int(entry.get(field) or 0) for field in ("input", "output", "cache_read", "cache_write"))
        cost = entry.get("cost_usd")
        if isinstance(cost, (int, float)):
            costs[key] = costs.get(key, 0.0) + float(cost)
            cost_seen.add(key)
    keys = [f"story-{r.get('number')}" for r in landed(rows)]
    counted = [key for key in keys if spent.get(key) or key in cost_seen]
    if not counted:
        return None
    avg_cost = sum(costs.get(key, 0.0) for key in counted) / len(counted) if any(key in cost_seen for key in counted) else None
    return sum(spent.get(key, 0) for key in counted) // len(counted), len(counted), avg_cost


def tokens_per_story(rows: list[dict], log: list[dict]) -> str:
    """All tokens and average cost per recently closed story, including review/fix sessions (#1152)."""
    found = tokens_per_closed(rows, log)
    if not found:
        return f"Tokens per closed story: not recorded for the last {DAYS} days."
    cost = f", average cost ${found[2]:.2f}" if found[2] is not None else ", average cost not recorded"
    return f"Tokens per closed story: {found[0]:,} across {found[1]} stories closed in the last {DAYS} days{cost}."


def handovers(now: datetime, folder: Path | None = None, days: int = DAYS) -> int:
    """The handover files written in the last DAYS: the stories that did not land and wait for a next session (#896)."""
    from lib import cmd_land
    since = (now - timedelta(days=days)).timestamp()
    return sum(1 for path in (folder or cmd_land.log_dir()).glob("handover-*.md") if path.stat().st_mtime >= since)


def typed_threads(folder: Path, now: datetime, projects: Path | None = None, days: int = DAYS) -> int:
    """The interactive Claude threads in FOLDER whose transcript changed in the last DAYS. A runner's headless builder is not a thread (#896)."""
    projects = projects or Path.home() / ".claude" / "projects"
    since = (now - timedelta(days=days)).timestamp()
    count = 0
    for path in status_page.project_dir(folder, projects).glob("*.jsonl"):
        try:
            if path.stat().st_mtime < since or any(row.get("entrypoint") == status_page.HEADLESS for row in status_page._first_lines(path)):
                continue
        except OSError:
            continue
        count += 1
    return count


def four_numbers(now: datetime, open_now: int, rows: list[dict], log: list[dict], folder: Path, projects: Path | None = None,
                 handover_dir: Path | None = None) -> dict:
    """The four revamp numbers for the last DAYS (#896): tokens per closed story (None when not recorded), handovers, threads typed into and open stories."""
    found = tokens_per_closed(rows, log)
    return {"tokens_per_closed": found[0] if found else None, "cost_per_closed": found[2] if found else None, "handovers": handovers(now, handover_dir),
            "threads": typed_threads(folder, now, projects), "open": open_now}


def numbers_line(numbers: dict) -> str:
    """The one line that prints the four revamp numbers (#896)."""
    tokens = numbers["tokens_per_closed"]
    spent = f"{tokens:,}" if tokens is not None else "not recorded"
    cost = f"${numbers['cost_per_closed']:.2f}" if numbers.get("cost_per_closed") is not None else "not recorded"
    big = f"{tokens / 1e6:.1f} million" if tokens is not None and tokens >= 1_000_000 else spent
    used = f"A finished story takes about {big} tokens and costs {cost}." if tokens is not None else "Tokens and cost per finished story: not recorded yet."
    return (f"{used} Work moved to a fresh session {numbers['handovers']} time{'s' if numbers['handovers'] != 1 else ''}, "
            f"you typed into {numbers['threads']} running thread{'s' if numbers['threads'] != 1 else ''}, and {numbers['open']} stories are open.")


def _slot_name(label: str) -> str:
    """'OliverCode #1084' for a validation slot labelled by its worktree folder 'OliverCode-1084', else the label as written."""
    found = re.fullmatch(r"(.+)-(\d+)", label)
    return f"{found.group(1)} #{found.group(2)}" if found else label or "another run"


def validation_slots() -> tuple[list[str], int]:
    """The labels of the validation slots held now and the slot count, read without reaping or waiting (#1112)."""
    try:
        held = [(validate_queue._read(p) or {}).get("label", "") for p in sorted(validate_queue.slots_dir().glob("slot-*.json"))]
        return held, validate_queue.slot_count()
    except OSError:
        return [], 1


def story_state(repo: str, n: str, rows: list[dict], began: float, holder: dict | None, slots: list[str], slot_total: int, github: str, elsewhere: list[str],
                own: bool = False) -> tuple[str, str]:
    """The state a building story is in and what holds it, '' when nothing does (#1112). A story is in the validation queue when its round ended and its worktree
    holds a slot. Only a claim of this repo, `own`, is read against this repo's lock, since another repo's claim is that repo's own build (#1122)."""
    mine = this_run(rows, began)
    last = mine[-1] if mine else {}
    if own and n.isdigit() and holder and int(n) not in (holder.get("building") or []) and elsewhere and not mine:
        return "Waiting for another repo", f"{elsewhere[0].rsplit('/', 1)[-1]} holds it"
    if github:
        return "Waiting for GitHub", "the GraphQL rate limit"
    if last.get("review") == "pass":
        return "Landing", ""
    if isinstance(last.get("round"), int):
        if f"{repo}-{n}" in slots:
            return "Validating", ""
        if f"{repo}-{n}" not in slots and slots and len(slots) >= slot_total:
            return "Waiting for validation", f"held by {_slot_name(slots[0])}"
        return "Reviewing", ""
    return "Building", ""


def state_lines(now: float, claims: dict, log: list[dict], issues: dict[str, dict], holder: dict | None, slots: list[str], slot_total: int, github: str, elsewhere: list[str],
                slug: str = "", notes: dict[str, str] | None = None) -> list[str]:
    """One line for each building story showing claimed time, activity time, and round count: 'OliverCode #1083 · M · Waiting for validation · claimed 9m, activity 2m, 1 round · held by OliverCode #1084' (#1122).
    Its warning from NOTES, when it has one, sits on an indented line under it."""
    lines = []
    for key, mine in sorted(claims.items()):
        n = key.rsplit("#", 1)[-1]
        repo = key.rpartition("#")[0].rsplit("/", 1)[-1]
        rows = [r for r in log if r.get("story") == f"story-{n}"]
        began = float(mine.get("since") or mine.get("at", 0))
        state, held = story_state(repo, n, rows, began, holder, slots, slot_total, github, elsewhere, key.rpartition("#")[0] == slug)
        since = max([began] + [_stamp(r, began) for r in this_run(rows, began)])
        size = cmd_groom.size_of(issues[n]) if n in issues else ""
        claimed_min = max(0, int((now - began) // 60))
        activity_min = max(0, int((now - since) // 60))
        rounds = round_count(rows)
        round_word = "round" if rounds == 1 else "rounds"
        time_summary = f"claimed {claimed_min}m, activity {activity_min}m, {rounds} {round_word}"
        lines.append(" · ".join([f"{repo} #{n}"] + ([size] if size else []) + [state, time_summary] + ([held] if held else [])))
        if (notes or {}).get(n):
            lines.append(f"  {notes[n]}")
    return lines


def _states(stamp: float, slug: str, claims: dict, log: list[dict], issues: dict, holder: dict, alive: bool, commits: dict) -> list[str]:
    """One line per building story, with what it is waiting on."""
    slots, slot_total = validation_slots()
    # run() stops before this on a REST hold, so the hold a story can wait on here is GraphQL's, which the runner's board calls spend
    return state_lines(stamp, claims, log, issues, holder, slots, slot_total, gh_budget.refusal("graphql"), run_lock.holders_elsewhere(slug, stamp) if slug else [],
                       slug, story_notes(stamp, claims, log, alive, holder, commits))


def live_lines(now: datetime, open_now: int, rows: list[dict], slug: str = "") -> list[str]:
    """The status lines for this machine right now, read from the claims, the run log, the process table, the run lock and the digest. The figures come
    first, then the Building section and the Last landed section, each set off by a blank line."""
    stamp = now.timestamp()
    log = run_log()
    from lib import gated
    holder = run_lock.active(slug, stamp) if slug else {}
    alive = runner_alive()
    ready = next_ready(digest_path(), held_numbers(stamp, slug))
    claims = live_claims(stamp)
    closed = closed_claims(claims, slug, rows)
    stale = [f"Stale claim: {key.rpartition('#')[0]} #{key.rpartition('#')[2]} is closed, so it is not building. Delete its entry in {claims_path()}." for key in sorted(closed)]
    claims = {k: v for k, v in claims.items() if k not in closed}
    issues = {str(i.get("number")): i for i in (open_issues.fetch(slug) or [])} if slug and claims else {}
    commits = {n: t for n in (key.rsplit("#", 1)[-1] for key in claims) if (t := last_commit(slug, n))}
    states = _states(stamp, slug, claims, log, issues, holder, alive, commits)
    building = ["", "Building:"] + (states or [idle_line(alive, open_now)]) + ([note] if (note := local_config.builder_note()) else []) + stale  # why the builder limit moved (#1158)
    building += [line] if (line := estimate_line(slug, stamp)) else []  # when the run finishes, or why nothing says (#1189)
    held = claim_lines(stamp, claims, github_claims(in_progress(stamp)))  # every live claim, with its holder (#1188)
    building += ["", "Claims:"] + held if held else []
    return [tokens_per_story(rows, log)] + gated.savings_lines() + building + [""] + last_lines(alive, (landed(rows) or [None])[0], ready, log, holder) + landed_today_lines(slug, stamp, log)


def last_commit(slug: str, n: str) -> float | None:
    """The time of the newest commit in story N's worktree, which the drain names after the repo, or None when there is none to read (#1086)."""
    from lib.placement import config as placement_config
    try:
        path = placement_config().worktrees / f"{slug.rsplit('/', 1)[-1]}-{n}"
        done = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%ct"], capture_output=True, text=True, timeout=10)
        return float(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def no_origin(folder: Path) -> str:
    """The error for a folder that is not a repo with a GitHub origin, and where to go next. It names the OliverCode checkout by path (#1094)."""
    return (f"Error: {folder} is not a repo with a GitHub origin. cd into a repo with a GitHub origin, "
            f"such as the OliverCode checkout at {OC_ROOT} or a registered fleet repo.")


def owner_steps(slug: str | None = None) -> list[dict]:
    """The open owner steps, after the ones whose story has closed are marked done (#1024)."""
    try:
        if slug:
            cmd_owner.clear_stories(slug, cmd_owner.story_closed)
        return [i for i in cmd_owner.items() if i["status"] == "open"]
    except (OSError, ValueError, KeyError):
        return []


def gather(slug: str, now: datetime, open_now: int, rows: list[dict], numbers: dict, steps: list[dict], ideas: int, city: bool) -> dict:
    """The figures `olivercode status` and City show, read once with no model call (#1177)."""
    stamp, log = now.timestamp(), run_log()
    claims = live_claims(stamp)
    claims = {k: v for k, v in claims.items() if k not in closed_claims(claims, slug, rows)}
    note = local_config.builder_note() or ""
    load = re.sub(r"^Builder limit \d+:\s*", "", note).rstrip(".")
    today = datetime.fromtimestamp(stamp).date()
    delivered = [{"story": str(r["story"]).rsplit("-", 1)[-1], "title": _text(r.get("title"), 60), "tokens": r["tokens"], "cost": r["cost"]}
                 for r in status_report.history(log, slug, stamp, days=2) if datetime.fromtimestamp(status_report._epoch(r.get("at"))).date() == today]
    newest = (landed(rows) or [None])[0]
    holder = run_lock.active(slug, stamp)
    issues = {str(i.get("number")): i for i in (open_issues.fetch(slug) or [])} if claims else {}
    commits = {n: t for n in (key.rsplit("#", 1)[-1] for key in claims) if (t := last_commit(slug, n))}
    lines = _states(stamp, slug, claims, log, issues, holder, runner_alive(), commits) if claims else []
    ready = next_ready(digest_path(), held_numbers(stamp, slug))
    return briefing.snapshot(slug=slug, now=now, open_now=open_now, rows=rows, numbers=numbers, steps=steps, today=delivered, ready=re.sub(r"^Next Ready:\s*", "", ready),
                             runner={"building": len(claims), "allowed": local_config.max_builders(), "load": load, "run": run_lock.describe(holder, stamp) if holder else "", "lines": lines}, ideas=ideas, city=city,
                             latest={"number": newest.get("number"), "title": _text(newest.get("title"), 70)} if newest else None)


def run(slug: str | None, count=issue_count.count_issues, fetch=recent, now: datetime | None = None, out=print, steps=None, ideas=None,
        folder: Path | None = None, numbers=None, city=None, brief=None) -> int:
    if not slug:
        out(no_origin(folder or Path.cwd()))
        return 1
    held = gh_budget.refusal("rest")
    if held:
        out(held)
        return 1
    now = now or datetime.now(timezone.utc)
    open_now = count(slug, "open")
    rows = fetch(slug, now - timedelta(days=DAYS))
    if open_now is None or rows is None:
        out(f"Error: the issues of {slug} were not read.")
        return 1
    snap = (brief or gather)(slug, now, open_now, rows, (numbers or (lambda: four_numbers(now, open_now, rows, run_log(), folder or Path.cwd())))(),
                             steps() if steps else owner_steps(slug), ideas() if ideas else _idea_count(), not (city or city_gap)())
    for line in briefing.text(snap):
        out(line)
    return 0


def _idea_count() -> int:
    try:
        return candidates.count()
    except (OSError, ValueError):
        return 0


def tokens(text: str) -> int:
    """The token count of TEXT by the estimate of DIGEST_CHARS characters a token. It is a ceiling, so the count never falls short."""
    return -(-len(text) // DIGEST_CHARS)


def digest_path() -> Path:
    return failure_log.home() / "status-digest.md"


def run_log() -> list[dict]:
    """The run-log rows, oldest first. A line that is not a JSON object is skipped, and a missing log reads as empty."""
    path = failure_log.home() / "run-log.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _text(value, limit: int = 160) -> str:
    """VALUE on one line, cut to LIMIT characters with an ellipsis."""
    flat = " ".join(str(value or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _decision_line(rec: dict) -> str:
    return (f"- {_text(rec.get('decision'), 40)}: chose {_text(rec.get('choice'), 40)} on {str(rec.get('created', ''))[:10]}"
            f" in thread {_text(rec.get('thread'), 40)}. Words: {_text(rec.get('words'))}")


def _run_line(row: dict) -> str:
    story = _text(row.get("story"), 20)
    if "review" in row:
        finding = "" if row["review"] == "pass" else f" Findings: {_text(row.get('findings'))}"
        return f"- {story} review {_text(row['review'], 20)}.{finding}"
    cost = row.get("cost_usd")
    spent = "cost unknown" if cost is None else f"cost ${float(cost):.2f}"
    return (f"- {story} round {_text(row.get('round'), 5)} on {_text(row.get('model'), 40)}: "
            f"{row.get('input', 0)} in and {row.get('output', 0)} out tokens, {spent}")


def landed(rows: list[dict]) -> list[dict]:
    """The issues closed in ROWS, newest close first."""
    return sorted((r for r in rows if r.get("closed_at")), key=lambda r: r["closed_at"], reverse=True)


def _story_line(row: dict, closed: bool = False) -> str:
    tag = f" ({str(row.get('closed_at'))[:10]})" if closed else ""
    return f"- {open_issues.priority(row) + ' ' if not closed and open_issues.priority(row) else ''}#{row.get('number')} {_text(row.get('title'), 90)}{tag}"


def open_lines(opened: list[dict]) -> list[str]:
    """The open stories in priority order, at most OPEN_SHOWN. An owner-gated story carries OWNER_GATED, so Next Ready passes over it."""
    return [_story_line(r) + (OWNER_GATED if open_issues.owner_gated(r) else "") for r in sorted(opened, key=open_issues.rank)[:OPEN_SHOWN]]


def city_gap() -> str:
    """The City reminder, or "" when City is set up or skipped (#1195). Lazy: cmd_guide imports this module's neighbors."""
    from lib import cmd_guide
    return cmd_guide.city_gap()


def candidate_line() -> str:
    """One line with the count of candidates waiting and the command that reviews them, or "" when none wait."""
    try:
        n = candidates.count()
    except (OSError, ValueError):
        return ""
    return f"- {n} candidate(s) wait: run `olivercode candidates` to review them." if n else ""


def waiting_lines(slug: str | None = None, closed=cmd_owner.story_closed) -> list[str]:
    """The owner-queue steps that are open, one line each, after the waits whose story has closed are marked done (#1024)."""
    try:
        if slug:
            cmd_owner.clear_stories(slug, closed)
        found = [i for i in cmd_owner.items() if i["status"] == "open"]
    except (OSError, ValueError, KeyError):
        return []
    return [f"- #{i['id']} {_text(i.get('step'), 120)}" for i in found[:DIGEST_ITEMS]] + ([f"- and {len(found) - DIGEST_ITEMS} more"] if len(found) > DIGEST_ITEMS else [])


def cached_open(slug: str, now: datetime, path: Path | None = None) -> int | None:
    """The open count of SLUG from the digest at PATH when it was written under DIGEST_TTL seconds ago, else None, so the caller reads GitHub (#1017)."""
    path = path or digest_path()
    try:
        if now.timestamp() - path.stat().st_mtime >= DIGEST_TTL:
            return None
        found = BOARD_RE.search(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(found.group(2)) if found and found.group(1) == slug else None


# shortcut: session_lines is no longer called by the digest or the hook; tests/test_status.py is outside story #1017's Files area and still tests it, so delete both together.
def session_lines(slug: str, open_now: int, rows: list[dict], path: Path) -> list[str]:
    """The three lines a new session prints: the open count, the last story landed and the digest to read."""
    last = landed(rows)
    done = f"Last story landed: #{last[0].get('number')} {_text(last[0].get('title'), 90)}." if last else f"No story landed in the last {DAYS} days."
    return [f"{slug}: {open_now} open stories.", done, f"Read {path} before acting."]


def _render(head: list[str], decisions: list[str], decision_total: int, runs: list[str], run_total: int) -> str:
    lines = head + [f"## Decisions, {len(decisions)} of {decision_total}"] + decisions + ["", f"## Run log, {len(runs)} of {run_total}"] + runs
    return "\n".join(lines) + "\n"


def _section(title: str, lines: list[str], none: str) -> list[str]:
    return [f"## {title}"] + (lines or [none]) + [""]


def build_digest(board: str, decisions: list[dict], runs: list[dict], now: datetime, opened: list[dict] | None = None,
                 rows: list[dict] | None = None, waiting: list[str] | None = None) -> str:
    """The digest text: the board line, the open stories in priority order, the last five landed, what waits on the owner, then the latest decisions and
    run-log rows, oldest first. It drops the oldest decisions and run rows until it fits DIGEST_TOKENS."""
    head = ["# Status digest", f"Written {now:%Y-%m-%d %H:%M} UTC.", f"Board: {board}", ""]
    head += _section(f"Open, {len(opened or [])} in priority order", open_lines(opened or []), "None.")
    head += _section("Landed, the last five", [_story_line(r, True) for r in landed(rows or [])[:DIGEST_ITEMS]], f"None in the last {DAYS} days.")
    head += _section("Waits on the owner", waiting or [], "Nothing.")
    dec = [_decision_line(r) for r in decisions[-DIGEST_ITEMS:]]
    run = [_run_line(r) for r in runs[-DIGEST_ITEMS:]]
    text = _render(head, dec, len(decisions), run, len(runs))
    while tokens(text) > DIGEST_TOKENS and (dec or run):
        if len(dec) >= len(run):
            dec = dec[1:]
        else:
            run = run[1:]
        text = _render(head, dec, len(decisions), run, len(runs))
    return text[: DIGEST_TOKENS * DIGEST_CHARS]


def write_digest(slug: str | None, count=issue_count.count_issues, fetch=recent, now: datetime | None = None, out=print,
                 decisions=relay.records, runs=run_log, target: Path | None = None, opened=open_issues.fetch, waiting=None, cands=None):
    """Write the status digest. Returns (path, text, open count), or None after printing why through OUT. It reads gh REST and local logs and calls no model."""
    if not slug:
        out("Error: this repo has no GitHub origin.")
        return None
    held = gh_budget.refusal("rest")
    if held:
        out(held)
        return None
    now = now or datetime.now(timezone.utc)
    open_now = count(slug, "open")
    rows = fetch(slug, now - timedelta(days=DAYS))
    stories = opened(slug)
    if open_now is None or rows is None or stories is None:
        out(f"Error: the issues of {slug} were not read.")
        return None
    path = target or digest_path()
    text = build_digest(f"{slug}: " + summary(open_now, rows, now), decisions(), runs(), now, stories, rows, (waiting or (lambda: waiting_lines(slug)))() + [l for l in [(cands or candidate_line)()] if l])
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as err:
        out(f"Error: the digest could not be written to {path}: {err}")
        return None
    return path, text, open_now


def digest(slug: str | None, out=print, **kw) -> int:
    """Write the status digest and print where it went and its token count."""
    done = write_digest(slug, out=out, **kw)
    if done is None:
        return 1
    path, text, _ = done
    out(f"Digest written to {path} ({tokens(text)} tokens, limit {DIGEST_TOKENS}).")
    return 0


def page(out=print) -> int:
    """Rewrite the status page from the saved run state, with no model call, and print its path."""
    from lib import city  # lazy: city imports this module too (#1097)
    state, log, now = status_report.load_state(), run_log(), datetime.now().timestamp()
    found = log + status_report.outside_landings(log, now)  # the commits that landed outside the runner show too (#996)
    page_text = status_report.render(state, found, now, published=status_report._last_publish(log), panel=city.panel_html(now))
    failure_log.write_atomic(status_report.page_path(), page_text)
    out(f"Status page written to {status_report.page_path()}.")
    return 0


def publish(argv: list[str], out=print, run=None) -> int:
    """Publish the page to City once and say whether the Artifact tool works headless, with the tokens and cost of the call (#990)."""
    if argv not in ([], ["--probe"]):
        out(USAGE)
        return 1
    page(out=lambda _text: None)
    found = status_report.publish(run=run, probe=argv == ["--probe"])
    if not found["ok"]:
        out(f"The Artifact tool did not publish headless: {found['detail']}. The local page at {status_report.page_path()} still works, and the step is in `olivercode owner list`.")
        return 1
    cost = "not recorded" if found["cost_usd"] is None else f"${found['cost_usd']:.4f}"
    out(f"The Artifact tool works headless. One publish cost {found['tokens']:,} tokens and {cost}.")
    return 0


def command_status(argv: list[str]) -> int:
    if "--open" in argv:  # the page covers this machine, so it opens from any folder and needs no GitHub origin (#996)
        return status_report.open_page()
    if argv[:1] == ["page"] and len(argv) == 1:
        return page()
    if argv[:1] == ["publish"]:
        return publish(argv[1:])
    root = Path.cwd()
    writes = argv[:1] == ["digest"]
    argv = argv[1:] if writes else argv
    if argv[:1] == ["--root"] and len(argv) == 2:
        root = Path(argv[1]).expanduser()
    elif argv:
        print(USAGE)
        return 1
    slug = repo_state.origin(root)
    return digest(slug) if writes else run(slug, folder=root)
