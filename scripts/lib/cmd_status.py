"""Launcher command `status`: the open story count, the landing rate, the tokens per closed story and the projected zero date for this repo, from gh REST only, with no model call.

`olivercode status [--root DIR]` reads the repo's open count and the stories opened and closed in the last seven days. A falling count prints the stories
landed per day and the date the count reaches zero at that pace. A flat or rising count prints the same figures and says the date is not reachable.

`olivercode status digest [--root DIR]` writes the same board figures with the open stories in priority order, the last five landed, what waits on the owner,
the latest decisions and the run-log rows to `status-digest.md` in the OliverCode home, at most DIGEST_TOKENS tokens. A new owner thread starts from that file
alone (#892), and the session-start hook refreshes it and prints `session_lines` (#985). It calls no model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import agent_loop, cmd_owner, failure_log, gh_budget, open_issues, relay, repo_state, run_lock
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import issue_count  # noqa: E402
import log_action  # noqa: E402

DAYS = 7
STALL_MINUTES = run_lock.STALL_MINUTES  # a building story with no claim or run-log row newer than this is reported as stalled (#987)
CLEAN_STOPS = ("", "end_turn", "completed")  # the stop reasons that end a round without trouble
DIGEST_TOKENS = 1500
DIGEST_CHARS = 3  # characters per token in the estimate: English runs near four, and ids, paths and code run shorter, so three keeps the digest under the limit
OPEN_SHOWN = 10  # the open stories the digest lists, highest priority first
DIGEST_ITEMS = 5  # the latest decisions and the latest run-log rows the digest keeps before it trims to the limit
MIN_SIZED = 5  # stories of one size that must reach staging in the window before status compares them (#1301)
BENCHMARKS = {"XS": (21, 0.14)}  # size -> (minutes, dollars) from the 23 Nov baseline in #1246; shortcut: only XS is measured, add a size once its baseline is set
USAGE = "Usage: olivercode status [--root DIR] | olivercode status digest [--root DIR] | olivercode status page [--fetch] [--open] [--root DIR]"


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
    closed = sum(1 for r in rows if r.get("state_reason") == "completed" and _after(r.get("closed_at"), since))
    rate = closed / days
    head = f"{open_now} open. In the last {days} days {closed} closed as completed and {opened} opened, so {rate:.1f} stories landed per day."
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


def runner_alive() -> bool:
    """True when a drain or dispatch process runs on this machine, read from the process table. No model call (#987)."""
    try:
        # -a: on macOS a plain pgrep skips its caller's ancestors, so a drain rewriting City never finds itself (#1379)
        return subprocess.run(["pgrep", "-fa", "olivercode (drain|dispatch)"], capture_output=True).returncode == 0
    except OSError:
        return False


def _epoch(value) -> float:
    """A run-log row's time in epoch seconds, or 0 for a row that has none (rows written before #987 carry no time)."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def next_ready(path: Path) -> str:
    """The first open story in the status digest, which is the next Ready story in priority order, or '' when no digest is written."""
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
        if line.startswith("- "):
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


def minutes(seconds: float) -> str:
    """SECONDS as whole minutes in words, never negative."""
    count = int(max(0, seconds) // 60)
    return "under a minute" if count == 0 else f"{count} minute{'' if count == 1 else 's'}"


def _story_rows(log: list[dict], story: str, upto: str = "") -> list[dict]:
    """The log rows of one story (its builder and reader rounds and its stage rows) from its latest claimed row, so an earlier attempt is not counted. `upto`
    ends them at the story's latest row of that stage."""
    rows = [r for r in log if r.get("story") in (story, f"{story}-review")]
    if upto:
        rows = rows[: max(i for i, r in enumerate(rows) if r.get("stage") == upto) + 1]
    return rows[max((i for i, r in enumerate(rows) if r.get("stage") == "claimed"), default=0):]


def _cost(rows: list[dict]) -> float:
    return sum(float(r.get("cost_usd") or 0) for r in rows if "round" in r)


def story_stage(n: str, claim_at: float, log: list[dict]) -> tuple[str, str | None, float, float]:
    """(stage, repo, since, began) for story N from its stage rows: `since` is when its latest stage began and `began` when it was claimed. A claim with no
    stage rows yet counts as claimed at the claim's own time (#1291)."""
    stages = [r for r in _story_rows(log, f"story-{n}") if r.get("stage")]
    if not stages:
        return "claimed", None, claim_at, claim_at
    began = _epoch(stages[0]["at"]) if stages[0]["stage"] == "claimed" else claim_at
    return stages[-1]["stage"], stages[-1].get("repo"), _epoch(stages[-1]["at"]), began


def building_line(n: str, slug: str, claim_at: float, log: list[dict], now: float) -> str:
    """'#7 in repo: validating for 3 minutes, 5 minutes in all' from the story's stage rows. The stage time runs from the latest stage row and the total from the
    claimed row (#1291)."""
    stage, repo, since, began = story_stage(n, claim_at, log)
    spent = _cost(_story_rows(log, f"story-{n}"))
    return (f"#{n} in {repo or slug.rsplit('/', 1)[-1]}: {stage} for {minutes(now - since)}, {minutes(now - began)} in all" + (f", ${spent:.2f} so far." if spent else "."))


STAGES = ("claimed", "building", "validating", "landing", "landed")  # the five stages a builder card's track shows, in order (#1357)


def builder_facts(n: str, claim_at: float, log: list[dict], now: float) -> dict:
    """What a builder card shows for story N, from its run-log rows since its claim: the stage and its place on the track, the time in that stage and in all,
    the model and route of its latest builder round, that round and why it runs, the spend with reader reviews, the size, and the tokens written to and read
    from cache. A figure the log does not hold is None, and the reason for a round is None until a round after the first has run (#1357)."""
    rows = _story_rows(log, f"story-{n}")
    own = [r for r in rows if r.get("story") == f"story-{n}"]
    rounds = [r for r in own if "round" in r]
    reviews = [r for r in own if "review" in r]
    stage, _, since, began = story_stage(n, claim_at, log)
    latest = rounds[-1] if rounds else {}
    current = latest.get("round") if isinstance(latest.get("round"), int) else None
    if current is None:
        why = None
    elif current == 1:
        why = "The first round of the build."
    elif reviews and reviews[-1]["review"] == "findings":
        why = f"The reviewer found defects in round {current - 1}."
    elif len(rounds) > 1 and rounds[-2].get("stop") not in CLEAN_STOPS:
        why = f"Round {current - 1} stopped with {rounds[-2]['stop']}."
    else:
        why = "The run log holds no reason for this round."
    return {"stage": stage, "place": STAGES.index(stage) if stage in STAGES else 0, "in_stage": minutes(now - since), "in_all": minutes(now - began),
            "model": latest.get("model"), "route": latest.get("route"), "round": current, "why": why, "cost": _cost(rows),
            "size": next((r["size"] for r in rows if r.get("size")), None),
            "written": sum(int(r.get("cache_write") or 0) for r in rows if "round" in r), "read": sum(int(r.get("cache_read") or 0) for r in rows if "round" in r)}


def landings(log: list[dict]) -> list[dict]:
    """The stories the runner landed, newest first, each as {story, repo, at, build, check, land, total, cost}. A stage's time is the `seconds` of the row after
    it, summed when the story built or validated more than once, and the cost is the log's rounds between the claim and the landing (#1291)."""
    found = []
    for story in dict.fromkeys(str(r.get("story")) for r in log if r.get("stage") == "landed"):
        rows = _story_rows(log, story, upto="landed")
        done = rows[-1]
        took = {"building": 0, "validating": 0, "landing": 0}
        stages = [r for r in rows if r.get("stage")]
        for before, row in zip(stages, stages[1:]):
            if before["stage"] in took:
                took[before["stage"]] += int(row.get("seconds") or 0)
        first = stages[0]
        found.append({"story": story, "repo": done.get("repo", ""), "at": _epoch(done.get("at")), "build": took["building"], "check": took["validating"],
                      "land": took["landing"], "total": _epoch(done.get("at")) - _epoch(first.get("at")), "cost": _cost(rows)})
    return sorted(found, key=lambda f: f["at"], reverse=True)


def landing_line(row: dict, label: str) -> str:
    cost = f" and ${row['cost']:.2f}" if row["cost"] else ""
    return (f"{label}: #{row['story'].rsplit('-', 1)[-1]} in {row['repo']} at {datetime.fromtimestamp(row['at'], timezone.utc):%Y-%m-%d %H:%M} UTC. "
            f"Building took {minutes(row['build'])}{cost}, validation {minutes(row['check'])}, landing {minutes(row['land'])}, {minutes(row['total'])} in all.")


def run_end_line(row: dict) -> str:
    """'Last run ended 2026-01-02 03:04 UTC: 3 stories landed, 1 stopped.' from a drain's run-end row (#1276)."""
    return f"Last run ended {datetime.fromtimestamp(_epoch(row.get('at')), timezone.utc):%Y-%m-%d %H:%M} UTC: {row.get('landed', 0)} {'story' if row.get('landed', 0) == 1 else 'stories'} landed, {row.get('stopped', 0)} stopped."


def watch_line(row: dict, log: list[dict]) -> str:
    """One plain line for a new stage row, reusing the status formatting: '#7 in repo: validating', '#7 landed in 3 minutes, $0.03' (#1276)."""
    if row["stage"] == "run-end":
        return run_end_line(row)
    n = str(row.get("story")).rsplit("-", 1)[-1]
    if row["stage"] == "landed":
        done = next((f for f in landings(log) if f["story"] == row["story"]), None)
        return f"#{n} landed" + (f" in {minutes(done['total'])}" + (f", ${done['cost']:.2f}" if done["cost"] else "") if done else "")
    return f"#{n} in {row.get('repo')}: {row['stage']}" + (f" ({row['reason']})" if row.get("reason") else "")


def command_watch(argv: list[str], sleep=time.sleep, out=print, alive=None) -> int:
    """`watch [REPO]` prints one line per stage row added to the run log from now on, and ends with the run-end row or when no drain holds the repo's
    run lock for three checks in a row. It reads the log only: no model and no GitHub call (#1276)."""
    from lib import cmd_drain
    repo = cmd_drain.resolve_repo(argv[0]) if argv else None
    if (argv and not repo) or len(argv) > 1:
        out("Usage: olivercode watch [REPO]")
        return 1
    slug = cmd_drain.slug_of(repo) if repo else ""
    alive = alive or (lambda: bool(run_lock.active(slug, time.time())) if slug else runner_alive())
    seen, idle = len(run_log()), 0
    while idle < 3:
        log = run_log()
        for row in log[seen:]:
            if row.get("stage") and (not repo or row.get("repo") == repo.name):
                out(watch_line(row, log))
                if row["stage"] == "run-end":
                    return 0
        seen = len(log)
        idle = 0 if alive() else idle + 1
        sleep(2)
    out("No drain is running" + (f" for {repo.name}" if repo else "") + ".")
    return 0


def idle_text(open_now: int | None) -> str:
    """The idle runner's line. The open count is left out when GitHub could not be read, so no figure is guessed (#1334)."""
    count = "" if open_now is None else f" and {open_now} stories are open"
    return f"Runner idle: no story is building{count}. Start it with `olivercode drain REPO`."


def building_block(now: float, claims: dict, log: list[dict], alive: bool, open_now: int | None, holder: dict | None = None) -> tuple[list[str], list[str]]:
    """The Building lines and their warnings. One line for each story building (its stage, its time in that stage and its time in all), or the idle or running
    line. A warning names a stalled builder, a claim with no runner and a last run that did not stop cleanly (#987). `holder` is the live run that holds the
    repo, if any (#1076). It reads only what it is given (#1334)."""
    lines, warnings = [], []
    for key, mine in sorted(claims.items()):
        n = key.rsplit("#", 1)[-1]
        rows = [r for r in log if r.get("story") == f"story-{n}"]
        progress = max([float(mine.get("at", 0))] + [_epoch(r.get("at")) for r in rows])
        if not alive:
            clears = datetime.fromtimestamp(float(mine.get("at", 0)) + log_action.CLAIM_HOURS * 3600, timezone.utc)
            lines.append(f"#{n} is claimed but nothing is building. The claim clears by itself at {clears:%H:%M} UTC.")
        elif (now - progress) / 60 > STALL_MINUTES:
            warnings.append(stall_line(n, mine, int((now - progress) // 60), holder))
        else:
            lines.append(building_line(n, key.rsplit("#", 1)[0], float(mine.get("at", 0)), log, now))
    if not lines:
        lines.append("The runner is running and no story is building." if alive else idle_text(open_now))
    if log and log[-1].get("stop", "") not in CLEAN_STOPS:
        story = str(log[-1].get("story", ""))
        resume = "" if holder else f" Resume it with `olivercode dispatch {story.rsplit('-', 1)[-1]}`."
        warnings.append(f"Warning: the last run on {story} stopped with {log[-1].get('stop')}.{resume}")
    return lines, warnings


def activity(now: float, claims: dict, log: list[dict], alive: bool, open_now: int | None, ready: str, holder: dict | None = None) -> list[str]:
    """The building lines, then the last three landings from the run log's landed rows and the next Ready story, then the warnings (#987). It reads only what
    it is given."""
    lines, warnings = building_block(now, claims, log, alive, open_now, holder)
    done = landings(log)[:3]
    lines += [landing_line(row, "Last landed" if i == 0 else "Landed before that") for i, row in enumerate(done)] or ["Last landed: none recorded yet."]
    ended = [r for r in log if r.get("stage") == "run-end"]
    if ended:
        lines.append(run_end_line(ended[-1]))
    if ready:
        lines.append(f"Next Ready: {ready}.")
    return lines + warnings


def tokens_per_story(rows: list[dict], log: list[dict]) -> str:
    """The tokens the runner spent per story closed in ROWS, from the run log's input and output counts for each of those stories (#982)."""
    spent = {}
    for entry in log:
        spent[str(entry.get("story"))] = spent.get(str(entry.get("story")), 0) + int(entry.get("input") or 0) + int(entry.get("output") or 0)
    counted = [spent[f"story-{r.get('number')}"] for r in landed(rows) if spent.get(f"story-{r.get('number')}")]
    if not counted:
        return f"Tokens per closed story: not recorded for the last {DAYS} days."
    return (f"Tokens per closed story: {sum(counted) // len(counted):,} across the {len(counted)} stories that recorded tokens, "
            f"out of {len(landed(rows))} closed in the last {DAYS} days.")


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def size_lines(log: list[dict], now: float, days: int = DAYS) -> list[str]:
    """One line per story size that reached staging (a landed row) in the last `days`: the median minutes from claim, rounds and cost, and the share that
    passed validation first time, beside the size's benchmark, or the count and 'too few' under MIN_SIZED. Rows with no size are left out (#1301)."""
    by_size: dict[str, list[dict]] = {}
    for story in dict.fromkeys(str(r.get("story")) for r in log if r.get("stage") == "landed"):
        rows = _story_rows(log, story, upto="landed")
        claimed = rows[0] if rows and rows[0].get("stage") == "claimed" else None
        if not claimed or not claimed.get("size") or _epoch(rows[-1].get("at")) < now - days * 86400:
            continue
        by_size.setdefault(claimed["size"], []).append({
            "minutes": (_epoch(rows[-1].get("at")) - _epoch(claimed.get("at"))) / 60, "rounds": sum(1 for r in rows if "round" in r and "stage" not in r),
            "cost": _cost(rows), "first": sum(1 for r in rows if r.get("stage") == "validating") <= 1})
    lines = []
    for size in sorted(by_size, key=lambda k: ["XS", "S", "M", "L", "XL"].index(k) if k in ("XS", "S", "M", "L", "XL") else 9):
        found = by_size[size]
        if len(found) < MIN_SIZED:
            lines.append(f"{size} stories: {len(found)} reached staging in the last {days} days, too few to compare.")
            continue
        bench = BENCHMARKS.get(size)
        against = f" Benchmark: {bench[0]} minutes and ${bench[1]:.2f}." if bench else " No benchmark is set for this size."
        ceiling = f" Ceiling: ${agent_loop.COST_CEILING[size]:.2f}." if size in agent_loop.COST_CEILING else ""
        lines.append(f"{size} stories: {len(found)} reached staging in the last {days} days. Median {median([f['minutes'] for f in found]):.1f} minutes, "
                     f"{median([f['rounds'] for f in found]):g} rounds, ${median([f['cost'] for f in found]):.2f}, "
                     f"{round(100 * sum(f['first'] for f in found) / len(found))}% passed validation first time.{against}{ceiling}")
    return lines


def landed_today(log: list[dict], now: float) -> list[dict]:
    """The stories landed on today's UTC date, newest first (#1334)."""
    today = datetime.fromtimestamp(now, timezone.utc).date()
    return [f for f in landings(log) if datetime.fromtimestamp(f["at"], timezone.utc).date() == today]


def live_lines(now: datetime, open_now: int | None, slug: str = "") -> list[str]:
    """The Building and Landed today sections for this machine, read from the claims, the run log, the process table, the run lock and the digest (#1334).
    A run log that cannot be read is named as unknown, and nothing is guessed from it."""
    stamp = now.timestamp()
    try:
        log = run_log()
    except (OSError, ValueError) as err:
        return [f"Building and landed today: unknown, because the run log could not be read ({err})."]
    holder = run_lock.active(slug, stamp) if slug else {}
    building, warnings = building_block(stamp, live_claims(stamp), log, runner_alive(), open_now, holder)
    ready = next_ready(digest_path())
    found, last = landed_today(log, stamp), landings(log)
    landed = [landing_line(row, "Landed") for row in found] or ["Nothing has landed today."]
    if not found:
        landed.append(landing_line(last[0], "Last landed") if last else "Last landed: none recorded yet.")
    ended = [r for r in log if r.get("stage") == "run-end"]
    lines = ["Building:"] + building + ([f"Next Ready: {ready}."] if ready else []) + warnings
    return lines + ["", "Landed today:"] + landed + ([run_end_line(ended[-1])] if ended else [])


def pace_lines(now: datetime, open_now: int | None, rows: list[dict] | None, slug: str) -> list[str]:
    """The Pace section: the open count, the landing rate and the estimated finish from GitHub, then the tokens, the gate savings and the size medians from
    the run log. A figure that cannot be read is named as unknown with why, and no figure is guessed (#1334)."""
    from lib import gated
    if open_now is None or rows is None:
        lines = [f"Open count, landing rate and finish date: unknown, because the issues of {slug} were not read from GitHub."]
    else:
        lines = [f"{slug}: " + summary(open_now, rows, now),
                 "The landing rate counts the stories closed as completed in the last 7 days, per day. The finish date divides the open count by the daily fall, so it is an estimate."]
    try:
        log = run_log()
    except (OSError, ValueError) as err:
        return ["Pace:"] + lines + [f"Tokens and sizes: unknown, because the run log could not be read ({err})."]
    tokens_line = "Tokens per closed story: unknown, because the closed issues were not read from GitHub." if rows is None else tokens_per_story(rows, log)
    return ["Pace:"] + lines + [tokens_line] + gated.savings_lines() + size_lines(log, now.timestamp())


def run(slug: str | None, count=issue_count.count_issues, fetch=recent, now: datetime | None = None, out=print, live=None,
        waiting=lambda: waiting_lines()) -> int:
    """The status page: what needs the owner first, then what is building and what landed today, then the pace. A figure that cannot be read from GitHub
    is printed as unknown, and the exit code is 1 (#1334)."""
    if not slug:
        out("Error: this repo has no GitHub origin.")
        return 1
    held = gh_budget.refusal("rest")
    if held:
        out(held)
        return 1
    now = now or datetime.now(timezone.utc)
    open_now = count(slug, "open")
    rows = fetch(slug, now - timedelta(days=DAYS))
    steps = waiting()  # a story a policy ask stopped waits on the owner, with the gate's name in its step (#1058)
    out("Needs you:")
    for line in steps or ["Nothing."]:
        out(line)
    out("")
    for line in (live(now, open_now, rows) if live else live_lines(now, open_now, slug)):
        out(line)
    out("")
    for line in pace_lines(now, open_now, rows, slug):
        out(line)
    held = run_lock.active(slug, now.timestamp())
    if held:
        out("Run: " + run_lock.describe(held, now.timestamp()))
    return 0 if open_now is not None and rows is not None else 1


def tokens(text: str) -> int:
    """The token count of TEXT by the estimate of DIGEST_CHARS characters a token. It is a ceiling, so the count never falls short."""
    return -(-len(text) // DIGEST_CHARS)


def digest_path() -> Path:
    return failure_log.home() / "status-digest.md"


def run_log() -> list[dict]:
    """The run-log rows, oldest first, its backup before the live log. A line that is not a JSON object is skipped, and a missing log reads as empty."""
    rows = []
    for line in agent_loop.run_log_lines():
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
    """The issues closed as completed in ROWS, newest close first. An issue closed as not planned did not land (#1246)."""
    return sorted((r for r in rows if r.get("closed_at") and r.get("state_reason") == "completed"), key=lambda r: r["closed_at"], reverse=True)


def _story_line(row: dict, closed: bool = False) -> str:
    tag = f" ({str(row.get('closed_at'))[:10]})" if closed else ""
    return f"- {open_issues.priority(row) + ' ' if not closed and open_issues.priority(row) else ''}#{row.get('number')} {_text(row.get('title'), 90)}{tag}"


def open_lines(opened: list[dict]) -> list[str]:
    """The open stories in priority order, at most OPEN_SHOWN."""
    return [_story_line(r) for r in sorted(opened, key=open_issues.rank)[:OPEN_SHOWN]]


def waiting_lines() -> list[str]:
    """The owner-queue steps that are open, one line each."""
    try:
        cmd_owner.retire_removed()  # a removed job's items close once, here, and are never listed again (#1246)
        found = cmd_owner.open_items()
    except (OSError, ValueError, KeyError):
        return []
    return [f"- #{i['id']} {_text(i.get('step'), 120)}" for i in found[:DIGEST_ITEMS]] + ([f"- and {len(found) - DIGEST_ITEMS} more"] if len(found) > DIGEST_ITEMS else [])


def session_lines(slug: str, open_now: int, log: list[dict], path: Path) -> list[str]:
    """The three lines a new session prints: the open count, the last story landed and the digest to read. The landing is the run log's latest landed row (#1291)."""
    last = landings(log)
    done = (f"Last story landed: #{last[0]['story'].rsplit('-', 1)[-1]} in {last[0]['repo']} at {datetime.fromtimestamp(last[0]['at'], timezone.utc):%Y-%m-%d %H:%M} UTC."
            if last else "No story landing is recorded in the run log yet.")
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
    run = [_run_line(r) for r in [r for r in runs if "stage" not in r][-DIGEST_ITEMS:]]
    text = _render(head, dec, len(decisions), run, len(runs))
    while tokens(text) > DIGEST_TOKENS and (dec or run):
        if len(dec) >= len(run):
            dec = dec[1:]
        else:
            run = run[1:]
        text = _render(head, dec, len(decisions), run, len(runs))
    return text[: DIGEST_TOKENS * DIGEST_CHARS]


def write_digest(slug: str | None, count=issue_count.count_issues, fetch=recent, now: datetime | None = None, out=print,
                 decisions=relay.records, runs=run_log, target: Path | None = None, opened=open_issues.fetch, waiting=waiting_lines):
    """Write the status digest. Returns (path, text, session lines), or None after printing why through OUT. It reads gh REST and local logs and calls no model."""
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
    log = runs()
    text = build_digest(f"{slug}: " + summary(open_now, rows, now), decisions(), log, now, stories, rows, waiting())
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as err:
        out(f"Error: the digest could not be written to {path}: {err}")
        return None
    return path, text, session_lines(slug, open_now, log, path)


def digest(slug: str | None, out=print, **kw) -> int:
    """Write the status digest and print where it went and its token count."""
    done = write_digest(slug, out=out, **kw)
    if done is None:
        return 1
    path, text, _ = done
    out(f"Digest written to {path} ({tokens(text)} tokens, limit {DIGEST_TOKENS}).")
    return 0


def command_status(argv: list[str]) -> int:
    if argv[:1] == ["page"]:
        from lib import city  # local import: city reads this module's figures
        return city.command_page(argv[1:])
    root = Path.cwd()
    writes = argv[:1] == ["digest"]
    argv = argv[1:] if writes else argv
    if argv[:1] == ["--root"] and len(argv) == 2:
        root = Path(argv[1]).expanduser()
    elif argv:
        print(USAGE)
        return 1
    slug = repo_state.origin(root)
    return digest(slug) if writes else run(slug)
