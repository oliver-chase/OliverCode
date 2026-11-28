"""Launcher command `status`: the open story count, the landing rate, the tokens per closed story and the projected zero date for this repo, from gh REST only, with no model call.

`olivercode status [--root DIR]` reads the repo's open count and the stories opened and closed in the last seven days. A falling count prints the stories
landed per day and the date the count reaches zero at that pace. A flat or rising count prints the same figures and says the date is not reachable.

`olivercode status digest [--root DIR]` writes the same board figures with the open stories in priority order, the last five landed, what waits on the owner,
the latest decisions and the run-log rows to `status-digest.md` in the OliverCode home, at most DIGEST_TOKENS tokens. A new owner thread starts from that file
alone (#892), and the session-start hook refreshes it and prints `session_lines` (#985). It calls no model.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import agent_loop, cmd_owner, failure_log, gh_budget, local_config, open_issues, relay, repo_state, run_lock
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
PRICE_NOTE = "API-price equivalent, not billed"  # the label on every dollar figure a build produces: builds run on the subscription, so nothing is billed (#1526)
YARDSTICK_NOTE = "API-price yardstick, not spend"  # the label on a benchmark or ceiling dollar figure
BENCHMARKS = {"XS": (21, 0.14)}  # size -> (minutes, dollars) from the 23 Nov baseline in #1246; shortcut: only XS is measured, add a size once its baseline is set
USAGE = "Usage: olivercode status [--root DIR] | olivercode status digest [--root DIR]"


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
        # -a: on macOS a plain pgrep skips its caller's ancestors, so a drain that rewrites a page never finds itself (#1379)
        return subprocess.run(["pgrep", "-fa", "olivercode (drain|dispatch)"], capture_output=True).returncode == 0
    except OSError:
        return False


def _epoch(value) -> float:
    """A run-log row's time in epoch seconds, or 0 for a row that has none (rows written before #987 carry no time)."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def repo_claims(claims: dict, slug: str) -> dict:
    """The claims of SLUG's repo, or every claim when no slug is given."""
    return {key: mine for key, mine in claims.items() if not slug or key.rsplit("#", 1)[0] == slug}


def next_ready(log: list[dict], slug: str = "", claims: dict = {}) -> str:
    """The first story with no live claim in CLAIMS among those SLUG's drain last said it can start (#1486, #1570), or of any repo's drain with no slug.
    '' when no drain has said, or it said none. A story landed or closed since then is left out."""
    # shortcut: the list is as old as the drain's last pass, so a card moved while no drain runs shows after the next run; read the board when status may spend a call.
    latest = {r.get("slug"): i for i, r in enumerate(log) if r.get("stage") == "queue" and (not slug or r.get("slug") == slug)}
    for i in sorted(latest.values(), reverse=True):
        row = log[i]
        done = {r.get("story") for r in log[i + 1:] if r.get("repo") == row.get("repo") and r.get("stage") in ("landed", "closed")}
        for n, line in row.get("ready", []):
            if f"{row.get('slug')}#{n}" not in claims and f"story-{n}" not in done:
                return line
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


def priced(rows: list[dict]) -> list[dict]:
    """The rows in ROWS that record a cost. A chat build's token rows hold none (#1533), so no cost figure counts them as free."""
    return [r for r in rows if r.get("cost_usd") is not None]


def _cost(rows: list[dict]) -> float:
    return sum(float(r["cost_usd"]) for r in priced(rows) if "round" in r)


def _tokens(rows: list[dict]) -> int:
    """The input, output, cache_read and cache_write tokens of the round rows in ROWS."""
    return sum(int(r.get(k) or 0) for r in rows if "round" in r for k in ("input", "output", "cache_read", "cache_write"))


def token_words(count: float) -> str:
    """COUNT as '1.2 million tokens' from a million up, else '310,000 tokens'."""
    count = round(count)
    return f"{count / 1_000_000:.1f} million tokens" if count >= 1_000_000 else f"{count:,} token{'' if count == 1 else 's'}"


def spend_words(tokens: float, cost: float) -> str:
    """'310,000 tokens and $0.77 (API-price equivalent, not billed)', with only the part that was recorded, or '' when neither was."""
    dollars = f"${cost:.2f} ({PRICE_NOTE})" if cost else ""
    return " and ".join(part for part in (token_words(tokens) if tokens else "", dollars) if part)


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
    rows = _story_rows(log, f"story-{n}")
    spent = spend_words(_tokens(rows), _cost(rows))
    return (f"#{n} in {repo or slug.rsplit('/', 1)[-1]}: {stage} for {minutes(now - since)}, {minutes(now - began)} in all" + (f", {spent} so far." if spent else "."))


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
                      "land": took["landing"], "total": _epoch(done.get("at")) - _epoch(first.get("at")), "cost": _cost(rows), "tokens": _tokens(rows)})
    return sorted(found, key=lambda f: f["at"], reverse=True)


def landing_detail(row: dict) -> str:
    """'Building took 3 minutes and $0.77, validation 1 minute, landing 2 minutes, 7 minutes in all.' for a landed row from landings (#1291)."""
    spent = spend_words(row.get("tokens", 0), row["cost"])
    cost = f" and {spent}" if spent else ""
    return f"Building took {minutes(row['build'])}{cost}, validation {minutes(row['check'])}, landing {minutes(row['land'])}, {minutes(row['total'])} in all."


def landing_line(row: dict, label: str) -> str:
    """'Last landed: #5 in r at 2026-11-22 04:17 EST. Building took ...', the landing's time in the owner's zone (#1486)."""
    return f"{label}: #{row['story'].rsplit('-', 1)[-1]} in {row['repo']} at {local_config.local_time(row['at'], '%Y-%m-%d %H:%M %Z')}. " + landing_detail(row)


def run_end_line(row: dict) -> str:
    """'Last run ended 2026-01-02 03:04 EST: 3 stories landed, 1 stopped.' from a drain's run-end row (#1276, #1486)."""
    return f"Last run ended {local_config.local_time(_epoch(row.get('at')), '%Y-%m-%d %H:%M %Z')}: {row.get('landed', 0)} {'story' if row.get('landed', 0) == 1 else 'stories'} landed, {row.get('stopped', 0)} stopped."


def run_total(rows: list[dict]) -> dict:
    """The last row of ROWS, one run from run_rows, with its landed and stopped counts summed over the run and the runs that restarted into it (#1490, #1570)."""
    ends = [r for r in rows if r["stage"] == "run-end"]
    return {**rows[-1], **{key: sum(r.get(key, 0) for r in ends) for key in ("landed", "stopped")}}


def last_run(log: list[dict], slug: str = "") -> list[str]:
    """run_end_line for the latest run-end row of SLUG's repo, or of any repo with no slug, counting only that repo's run, or nothing (#1570). A row
    written before run-end rows named their slug is matched by the repo's name."""
    for i in range(len(log) - 1, -1, -1):
        row = log[i]
        if row.get("stage") == "run-end" and (not slug or (row["slug"] == slug if "slug" in row else row.get("repo") == slug.rsplit("/", 1)[-1])):
            return [run_end_line(run_total(run_rows(log[:i + 1], row.get("repo"))))]
    return []


def skip_text(row: dict) -> str:
    """' Skipped #1: its board Status is Backlog, not Ready.' for each story a run-end row says the run did not start, or '' (#1510)."""
    return "".join(f" Skipped #{n}: {why}." for n, why in row.get("skipped", {}).items())


def watch_line(row: dict, log: list[dict]) -> str:
    """One plain line for a new stage row, stamped with the row's time in the owner's zone (#1486): '14:40 EST #7 in repo: validating', '14:40 EST #7 in repo:
    landed. Building took ...', '14:40 EST #7 in repo: stopped (Landing refused: weakened-test)'. A run-end row already carries its time (#1276),
    counts the runs in LOG that restarted into it (#1570) and is followed by the stories its run skipped (#1510). LOG ends at a run-end ROW."""
    if row["stage"] == "run-end":
        return run_end_line(run_total(run_rows(log, row.get("repo")))) + skip_text(row)
    stamp = local_config.local_time(_epoch(row.get("at")) or time.time(), "%H:%M %Z")
    n = str(row.get("story")).rsplit("-", 1)[-1]
    if row["stage"] == "landed":
        done = next((f for f in landings(log) if f["story"] == row["story"]), None)
        return f"{stamp} #{n} in {row.get('repo')}: landed" + (f". {landing_detail(done)}" if done else ".")
    return f"{stamp} #{n} in {row.get('repo')}: {row['stage']}" + (f" ({row['reason']})" if row.get("reason") else "")


def _restarting(rows: list[dict]) -> bool:
    """True when ROWS end in the run-end row of a drain that starts itself again (#1480)."""
    return [r["stage"] for r in rows[-2:]] == ["restarting", "run-end"]


def _drain_holds(rows: list[dict], alive) -> bool:
    """True while a drain holds the repo: its run lock, or a drain process between a restart's two runs (#1494, #1535)."""
    # shortcut: between a restart's two runs any drain process counts as alive, so match this repo's process if another repo's drain ever holds a watch open.
    return alive() or (_restarting(rows) and runner_alive())


def run_rows(log: list[dict], repo: str) -> list[dict]:
    """REPO's stage rows of its latest run, with the runs before it that restarted into it (#1490)."""
    rows = [r for r in log if r.get("repo") == repo and r.get("stage")]
    start = 0
    for i in range(len(rows) - 1):
        if rows[i]["stage"] == "run-end" and not _restarting(rows[:i + 1]):
            start = i + 1
    return rows[start:]


def next_step(repo: str, counted: dict, skipped: dict, limited: bool) -> str:
    """The `Next:` line after a run's end (#1571). A run that landed a story and left one to build or retry tells the session to start the drain
    again, unless a usage limit or GitHub hold stopped it. Otherwise the step names the owner's work, or the step that needs no owner."""
    can_build = counted["stopped"] > 0 or any(k in ("blocker", "other") for k in skipped.values())
    if not can_build:
        size = ", ".join(f"#{n}" for n, k in skipped.items() if k == "size")
        owner = ", ".join(f"#{n}" for n, k in skipped.items() if k == "owner")
        steps = ([f"split {size}, which needs splitting"] if size else []) + ([f"name {owner} to the owner once, as owner-gated"] if owner else [])
        return f"Next: {', and '.join(steps)}." if steps else "Next: nothing is left to build."
    if counted["landed"] and not limited:
        return f"Next: start the drain again without asking the owner: `olivercode drain {repo}`."
    return "Next: wait for the usage limit or GitHub hold to clear, or diagnose the failure and file it; no owner step is needed."


def exit_line(repo: str, rows: list[dict]) -> str:
    """The lines `watch --until-exit` prints for the run in ROWS: its landed and stopped counts and why it ended (#1490), then each story it
    skipped and why (#1510), then a `Next:` line (#1571). A run with no run-end row is counted from its story rows."""
    if not rows:
        return f"No drain is running for {repo}."
    last = rows[-1]
    if last["stage"] == "run-end":
        counted = run_total(rows)
        why = "It logged a restart and the new run never started." if _restarting(rows) else last.get("reason") or "No story it could start was left."
        limited = any(word in (last.get("reason") or "") for word in ("usage limit", "rate limit"))
    else:
        done = {r.get("story") for r in rows if r["stage"] in ("landed", "closed")}
        stopped = {r.get("story") for r in rows if r["stage"] == "stopped" and str(r.get("story")).startswith("story-")} - done
        counted = {**last, "landed": len(done), "stopped": len(stopped)}
        why = "It logged no run-end row, so no drain finished it."
        limited = False
    return f"{run_end_line(counted)} {' '.join(why.split())}{skip_text(last)}\n{next_step(repo, counted, last.get('skipped', {}), limited)}"


def wait_for_exit(repo: str, alive, sleep, out) -> int:
    """Print nothing while REPO's drain runs, then exit_line once: at a new run-end row, or when no drain holds the run lock for three checks in a row.
    A run that ends by restarting is followed into the new run (#1490)."""
    def ends(log: list[dict]) -> list[dict]:
        return [r for r in log if r.get("repo") == repo and r.get("stage") == "run-end"]

    before = ends(run_log())[-1:]
    idle = 0
    while idle < 3:
        log = run_log()
        rows = run_rows(log, repo)
        if rows and rows[-1]["stage"] == "run-end" and ends(log)[-1:] != before and not _restarting(rows):
            break
        idle = 0 if _drain_holds(rows, alive) else idle + 1
        sleep(2)
    out(exit_line(repo, run_rows(run_log(), repo)))
    return 0


def command_watch(argv: list[str], sleep=time.sleep, out=print, alive=None) -> int:
    """`watch [REPO]` opens with what is building, the last three landings and the next Ready story, as status shows them (#1486). Then it prints one
    line per stage row added to the run log from now on, each stamped in the owner's zone, and ends with the run-end row or when no drain holds the repo's
    run lock for three checks in a row. A queue row is not printed. It reads the log and the claims only: no model and no GitHub call (#1276, #1486).
    `watch REPO --until-exit` prints only the one line of wait_for_exit, which is the form a session runs in the background (#1490)."""
    from lib import cmd_drain
    until_exit = "--until-exit" in argv
    argv = [a for a in argv if a != "--until-exit"]
    repo = cmd_drain.resolve_repo(argv[0]) if argv else None
    if (argv and not repo) or len(argv) > 1 or (until_exit and not repo):
        out("Usage: olivercode watch [REPO] | olivercode watch REPO --until-exit")
        return 1
    slug = cmd_drain.slug_of(repo) if repo else ""
    alive = alive or (lambda: bool(run_lock.active(slug, time.time())) if slug else runner_alive())
    if until_exit:
        return wait_for_exit(repo.name, alive, sleep, out)
    log = run_log()
    stamp = time.time()
    claims = repo_claims(live_claims(stamp), slug)
    for line in activity(stamp, claims, log, alive(), None, next_ready(log, slug, claims), run_lock.active(slug, stamp) if slug else None, slug):
        out(line)
    seen, idle, prev = len(log), 0, None
    while idle < 3:
        log = run_log()
        for i, row in enumerate(log[seen:], seen):
            if row.get("stage") not in (None, "queue") and (not repo or row.get("repo") == repo.name):
                out(watch_line(row, log[:i + 1]))
                # a run-end right after a restarting row is the old run handing over to the new one, so the watch keeps reading (#1494)
                ends = row["stage"] == "run-end" and prev != "restarting"
                prev = row["stage"]
                if ends:
                    return 0
        seen = len(log)
        # a restart's gap counts as alive too, so the watch keeps following the new run (#1535)
        idle = 0 if _drain_holds(run_rows(log, repo.name) if repo else [], alive) else idle + 1
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
            lines.append(f"#{n} is claimed but nothing is building. The claim clears by itself at {local_config.local_time(clears)}.")
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


def activity(now: float, claims: dict, log: list[dict], alive: bool, open_now: int | None, ready: str, holder: dict | None = None,
             slug: str = "") -> list[str]:
    """The building lines, then the last three landings from the run log's landed rows, the last run of SLUG's repo and the next Ready story, then the
    warnings (#987). It reads only what it is given."""
    lines, warnings = building_block(now, claims, log, alive, open_now, holder)
    done = landings(log)[:3]
    lines += [landing_line(row, "Last landed" if i == 0 else "Landed before that") for i, row in enumerate(done)] or ["Last landed: none recorded yet."]
    lines += last_run(log, slug)
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
            "cost": _cost(rows), "priced": bool(priced(rows)), "tokens": _tokens(rows), "first": sum(1 for r in rows if r.get("stage") == "validating") <= 1})
    lines = []
    for size in sorted(by_size, key=lambda k: ["XS", "S", "M", "L", "XL"].index(k) if k in ("XS", "S", "M", "L", "XL") else 9):
        found = by_size[size]
        if len(found) < MIN_SIZED:
            lines.append(f"{size} stories: {len(found)} reached staging in the last {days} days, too few to compare.")
            continue
        bench = BENCHMARKS.get(size)
        costs = [f["cost"] for f in found if f["priced"]]
        against = f" Benchmark: {bench[0]} minutes and ${bench[1]:.2f} ({YARDSTICK_NOTE})." if bench else " No benchmark is set for this size."
        ceiling = f" Ceiling: ${agent_loop.COST_CEILING[size]:.2f} ({YARDSTICK_NOTE})." if size in agent_loop.COST_CEILING else ""
        lines.append(f"{size} stories: {len(found)} reached staging in the last {days} days. Median {statistics.median([f['minutes'] for f in found]):.1f} minutes, "
                     f"{statistics.median([f['rounds'] for f in found]):g} rounds, "
                     f"{spend_words(statistics.median([f['tokens'] for f in found]), statistics.median(costs) if costs else 0) or 'no tokens or cost recorded'}, "
                     f"{round(100 * sum(f['first'] for f in found) / len(found))}% passed validation first time.{against}{ceiling}")
    return lines


def landed_today(log: list[dict], now: float) -> list[dict]:
    """The stories landed on today's date in the owner's zone, newest first (#1334, #1486)."""
    today = local_config.local_time(now, "%Y-%m-%d")
    return [f for f in landings(log) if local_config.local_time(f["at"], "%Y-%m-%d") == today]


def live_lines(now: datetime, open_now: int | None, slug: str = "") -> list[str]:
    """The Building and Landed today sections for this machine, read from the claims, the run log, the process table and the run lock (#1334).
    A run log that cannot be read is named as unknown, and nothing is guessed from it."""
    stamp = now.timestamp()
    try:
        log = run_log()
    except (OSError, ValueError) as err:
        return [f"Building and landed today: unknown, because the run log could not be read ({err})."]
    holder = run_lock.active(slug, stamp) if slug else {}
    claims = live_claims(stamp)
    building, warnings = building_block(stamp, claims, log, runner_alive(), open_now, holder)
    ready = next_ready(log, slug, claims)
    found, last = landed_today(log, stamp), landings(log)
    landed = [landing_line(row, "Landed") for row in found] or ["Nothing has landed today."]
    if not found:
        landed.append(landing_line(last[0], "Last landed") if last else "Last landed: none recorded yet.")
    lines = ["Building:"] + building + ([f"Next Ready: {ready}."] if ready else []) + warnings
    return lines + ["", "Landed today:"] + landed + last_run(log, slug)


def pace_lines(now: datetime, open_now: int | None, rows: list[dict] | None, slug: str) -> list[str]:
    """The Pace section: the open count, the landing rate and the estimated finish from GitHub, then the tokens and the size medians from the run log.
    A figure that cannot be read is named as unknown with why, and no figure is guessed (#1334)."""
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
    return ["Pace:"] + lines + [tokens_line] + size_lines(log, now.timestamp())


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
    spent = "cost unknown" if cost is None else f"cost ${float(cost):.2f} ({PRICE_NOTE})"
    return (f"- {story} round {_text(row.get('round'), 5)} on {_text(row.get('model'), 40)}: {row.get('input', 0)} input, {row.get('output', 0)} output, "
            f"{row.get('cache_read', 0)} cache read and {row.get('cache_write', 0)} cache write tokens, {spent}")


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
    done = (f"Last story landed: #{last[0]['story'].rsplit('-', 1)[-1]} in {last[0]['repo']} at {local_config.local_time(last[0]['at'], '%Y-%m-%d %H:%M %Z')}."
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
