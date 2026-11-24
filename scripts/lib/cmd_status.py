"""Launcher command `status`: the open story count, the landing rate, the tokens per closed story and the projected zero date for this repo, from gh REST only, with no model call.

`olivercode status [--root DIR]` reads the repo's open count and the stories opened and closed in the last seven days. A falling count prints the stories
landed per day and the date the count reaches zero at that pace. A flat or rising count prints the same figures and says the date is not reachable.

`olivercode status digest [--root DIR]` writes the same board figures with the open stories in priority order, the last five landed, what waits on the owner,
the latest decisions and the run-log rows to `status-digest.md` in the OliverCode home, at most DIGEST_TOKENS tokens. A new owner thread starts from that file
alone (#892). The session-start hook refreshes it once it is older than DIGEST_TTL and prints one line with the open count (#985, #1017). It calls no model.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import candidates, cmd_owner, failure_log, gh_budget, open_issues, relay, repo_state, run_lock
from lib.local_config import OC_ROOT

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import issue_count  # noqa: E402
import log_action  # noqa: E402

DAYS = 7
STALL_MINUTES = run_lock.STALL_MINUTES  # a building story whose progress has not moved for this long is reported as stalled (#987, #1020)
CLEAN_STOPS = ("", "end_turn", "completed")  # the stop reasons that end a round without trouble
DIGEST_TOKENS = 1500
DIGEST_TTL = 600  # seconds a written digest serves a new session, so a session that starts soon after another makes no GitHub call (#1017)
BOARD_RE = re.compile(r"^Board: (\S+): (\d+) open\.", re.MULTILINE)  # the repo and open count the digest's board line states
DIGEST_CHARS = 3  # characters per token in the estimate: English runs near four, and ids, paths and code run shorter, so three keeps the digest under the limit
OPEN_SHOWN = 10  # the open stories the digest lists, highest priority first
DIGEST_ITEMS = 5  # the latest decisions and the latest run-log rows the digest keeps before it trims to the limit
OWNER_GATED = " (owner gated)"  # the digest's mark on a story that waits on the owner, so Next Ready skips it (#1020)
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


def runner_alive() -> bool:
    """True when a drain or dispatch process runs on this machine, read from the process table. No model call (#987)."""
    try:
        return subprocess.run(["pgrep", "-f", "olivercode (drain|dispatch)"], capture_output=True).returncode == 0
    except OSError:
        return False


def held_numbers(now: float) -> set[int]:
    """The story numbers that a live claim or an open owner-queue step holds back from Ready. A claim names its story in its key, and a policy stop names
    its story in its step (#1058)."""
    held = {int(key.rsplit("#", 1)[-1]) for key in live_claims(now) if key.rsplit("#", 1)[-1].isdigit()}
    try:
        steps = [i for i in cmd_owner.items() if i["status"] == "open"]
    except (OSError, ValueError, KeyError):
        steps = []
    return held | {int(n) for i in steps for n in re.findall(r"Story #(\d+)", str(i.get("step", "")))}


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


def activity(now: float, claims: dict, log: list[dict], alive: bool, open_now: int, ready: str, landed_row: dict | None, holder: dict | None = None) -> list[str]:
    """The live status lines: one line for each story building (its minutes, its round), or the idle or running line, then the last landing and the next
    Ready story, then a warning for a stalled builder, a claim with no runner and a last run that did not stop cleanly (#987). A builder's progress is the newer of
    its claim's time and the live holder's heartbeat, when the holder is building it (#1020). `holder` is the live run that holds the repo, if any (#1076).
    It reads only what it is given."""
    lines, warnings = [], []
    for key, mine in sorted(claims.items()):
        n = key.rsplit("#", 1)[-1]
        rows = [r for r in log if r.get("story") == f"story-{n}"]
        progress = float(mine.get("at", 0))
        if holder and n.isdigit() and int(n) in (holder.get("building") or []):
            progress = max(progress, float(holder.get("beat", 0)))  # the live runner beats while it builds the story (#1020)
        if not alive:
            warnings.append(f"Warning: #{n} holds a claim by {mine.get('agent')} but no drain or dispatch process is running. The claim expires by itself "
                            f"after {log_action.CLAIM_HOURS} hours, or delete its entry in {claims_path()} to release it now.")
        elif (now - progress) / 60 > STALL_MINUTES:
            warnings.append(stall_line(n, mine, int((now - progress) // 60), holder))
        else:
            began = float(mine.get("since") or mine.get("at", 0))  # the claim's start, which a renewal keeps (#1093)
            round_ = next((r["round"] for r in reversed(rows) if isinstance(r.get("round"), int)), 0)  # a row with no round says nothing (#1093)
            lines.append(f"Building #{n} for {max(0, int((now - began) // 60))} minutes on round {round_}.")
    if not lines:
        lines.append("The runner is running and no story is building." if alive else
                     f"Runner idle: no story is building and {open_now} stories are open. Start it with `olivercode drain REPO`.")
    if landed_row:
        last = f"Last landed: #{landed_row.get('number')} {_text(landed_row.get('title'), 90)}."
    else:
        last = f"Last landed: none in the last {DAYS} days."
    lines.append(last + (f" Next Ready: {ready}." if ready else ""))
    if log and log[-1].get("stop", "") not in CLEAN_STOPS:
        story = str(log[-1].get("story", ""))
        resume = "" if holder else f" Resume it with `olivercode dispatch {story.rsplit('-', 1)[-1]}`."
        warnings.append(f"Warning: the last run on {story} stopped with {log[-1].get('stop')}.{resume}")
    return lines + warnings


def tokens_per_story(rows: list[dict], log: list[dict]) -> str:
    """The tokens the runner spent per story closed in ROWS, from the run log's input and output counts for each of those stories (#982)."""
    spent = {}
    for entry in log:
        spent[str(entry.get("story"))] = spent.get(str(entry.get("story")), 0) + int(entry.get("input") or 0) + int(entry.get("output") or 0)
    counted = [spent[f"story-{r.get('number')}"] for r in landed(rows) if spent.get(f"story-{r.get('number')}")]
    if not counted:
        return f"Tokens per closed story: not recorded for the last {DAYS} days."
    return f"Tokens per closed story: {sum(counted) // len(counted):,} across {len(counted)} stories closed in the last {DAYS} days."


def live_lines(now: datetime, open_now: int, rows: list[dict], slug: str = "") -> list[str]:
    """The status lines for this machine right now, read from the claims, the run log, the process table, the run lock and the digest."""
    stamp = now.timestamp()
    log = run_log()
    from lib import gated
    holder = run_lock.active(slug, stamp) if slug else {}
    ready = next_ready(digest_path(), held_numbers(stamp))
    return [tokens_per_story(rows, log)] + gated.savings_lines() + activity(stamp, live_claims(stamp), log, runner_alive(), open_now, ready,
                                                                           (landed(rows) or [None])[0], holder)


def run(slug: str | None, count=issue_count.count_issues, fetch=recent, now: datetime | None = None, out=print, live=None,
        waiting=None, cands=None) -> int:
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
    if open_now is None or rows is None:
        out(f"Error: the issues of {slug} were not read.")
        return 1
    out(f"{slug}: " + summary(open_now, rows, now))
    for line in (live(now, open_now, rows) if live else live_lines(now, open_now, rows, slug)):
        out(line)
    steps = (waiting or (lambda: waiting_lines(slug)))()  # a story a policy ask stopped waits on the owner, with the gate's name in its step (#1058)
    if steps:
        out("Waits on the owner:")
        for line in steps:
            out(line)
    line = (cands or candidate_line)()
    if line:
        out("Candidates:")
        out(line)
    held = run_lock.active(slug, now.timestamp())
    if held:
        out("Run: " + run_lock.describe(held, now.timestamp()))
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
