"""Launcher command `dispatch`: build one board story headless, through the same `work_story` that `drain` uses.

`olivercode dispatch N [--from SID] [--dry-run]` reads the story, refuses a closed or claimed story or a busy machine, claims it and builds it in one fresh headless session. The runner validates the commit,
lands it, comments, closes the story and releases the claim, exactly as a drain does.
"""

from __future__ import annotations

import ast
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from lib import agent_loop, backlog_setup, failure_log, intake, gh_budget, local_config, open_issues, run_lock
from lib.local_config import OC_ROOT
from lib.placement import config as placement_config

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
sys.path.insert(0, str(OC_ROOT / "skills" / "audit" / "scripts"))
import batch_project  # noqa: E402
import log_action  # noqa: E402

USAGE = "Usage: olivercode dispatch N [--from SID] [--dry-run] | olivercode dispatch --plan"
HEADLESS_RULES = """Builder rules:
- Commit on the branch only, by explicit path, and reference the story as (#{n}) in every message
- Commit and stop. The runner validates the commit, lands it with `olivercode land`, logs the story and closes it, so you never validate, land, log or close
- Leave production deploys, payments, credentials and the owner's rules files (CLAUDE.md, VOICE.md, DESIGN.md) to the owner
- Read an issue and its comments over REST with `gh api repos/OWNER/REPO/issues/N` and `.../issues/N/comments`, which spend no GraphQL points. `gh issue` and `gh project` spend the shared 5,000-point GraphQL hour
- {model}. When you wait for a result, end your turn and never poll
- Reuse before you write: check in order whether the code needs to exist, already exists here, is in the standard library, is in an installed dependency, or fits one line. Write the minimum only after that
- Extend the function or file the story names, remove what the change makes dead, and add no module, command, file or config the story does not ask for
- A deliberate shortcut gets a comment `shortcut: <limit>, <when to upgrade>`, which the audit lists as debt and never flags as over-engineering
- Report the branch and the commits
- Start no session. When you need a decision, choose the option you recommend and write the reason in the commit message"""


def headless_brief(n: int, story: dict, agent: str, worktree=None, extras: str = "", note: str = "") -> str:
    """The one brief a headless builder gets, for `dispatch` and `drain` alike (#877): the story, what it names, and rules that end at the commit.
    `extras` is text between the story and the rules (code excerpts, owner decisions) and `note` says why an earlier builder stopped."""
    builder, reader, why = intake.models(story, f"story-{n}")  # the same names the runner starts (#1015), and the rule that chose the builder (#1026)
    review = agent_loop.review_mode(intake.size_of(story), story.get("labels") or (), intake.files_area(story.get("body") or ""), intake.priority_of(story))
    review_note = (f"a fresh {reader.capitalize()} reader reads the commit before it lands" if review == "full"
                   else "repository validation and commit gates check the commit before it lands")
    model = f"Run on {builder.capitalize()} ({why}), and {review_note}"
    body = (story.get("body") or "").strip()
    text = f"Story #{n}: {story['title']}\n\n{body}\n\n{extras + chr(10) if extras else ''}{HEADLESS_RULES.format(n=n, model=model, agent=agent)}\n"
    if note:
        text += f"\nAn earlier builder stopped here: {note}\nContinue from the work already in this worktree.\n"
    return text


EXCERPT_CHARS = 6000  # the most code a brief carries (#887)
CALLERS_PER_FUNCTION = 4


def _functions(path: Path, body: str) -> list[tuple[str, str]]:
    """(name, source) of each function in a Python file whose name the story text mentions."""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    return [(node.name, "\n".join(lines[node.lineno - 1:node.end_lineno])) for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.search(rf"\b{re.escape(node.name)}\b", body)]


def _callers(repo: Path, name: str, skip: str) -> list[str]:
    """Up to CALLERS_PER_FUNCTION `file:line: code` lines in the repo that call the function, not counting its own definition."""
    try:
        ran = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-E", rf"(^|[^A-Za-z0-9_]){name}\(", "--", "*.py"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    found = [l for l in ran.stdout.splitlines() if not re.search(rf"def {re.escape(name)}\b", l) and not l.startswith(skip + ":")]
    return found[:CALLERS_PER_FUNCTION]


def file_excerpts(body: str, repo) -> str:
    """The functions the story names in its Files area, with their callers, bounded to EXCERPT_CHARS. '' when the story names none (#887)."""
    repo, parts = Path(repo), []
    for rel in intake.files_area(body):
        if not rel.endswith(".py"):
            continue
        for name, source in _functions(repo / rel, body):
            callers = _callers(repo, name, rel)
            parts.append(f"{rel}: {name}\n```python\n{source}\n```" + ("\nCallers:\n" + "\n".join(f"  {c}" for c in callers) if callers else ""))
    out = ""
    for part in parts:
        if len(out) + len(part) > EXCERPT_CHARS:
            break
        out += part + "\n\n"
    return f"Code the story names:\n\n{out}" if out else ""


def gh(args: list[str]):
    """Run `gh`, refusing first while the shared GitHub hold is on."""
    why = gh_budget.refusal()
    if why:
        return subprocess.CompletedProcess(args, 1, "", why)
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def _toplevel() -> Path:
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else OC_ROOT


def origin_slug(repo, slug: str) -> str:
    """The repo whose issues are read: a fork inherits upstream's config file, so the origin remote names it (#754, #1012)."""
    origin = backlog_setup.origin_owner_name(repo)
    if origin and f"{origin[0]}/{origin[1]}".lower() != slug.lower():
        return f"{origin[0]}/{origin[1]}"
    return slug


def _parse(argv: list[str]):
    sid, dry, pos, i = "", False, [], 0
    while i < len(argv):
        if argv[i] == "--from" and i + 1 < len(argv):
            sid, i = argv[i + 1], i + 2
        elif argv[i] == "--dry-run":
            dry, i = True, i + 1
        elif argv[i].startswith("--"):
            return None
        else:
            pos.append(argv[i])
            i += 1
    return (int(pos[0]), sid, dry) if len(pos) == 1 and pos[0].isdigit() and int(pos[0]) > 0 else None


def is_engine(repo) -> bool:
    """True when the runner must refuse `repo`: any OliverCode checkout, unless this machine's settings name an engineBranch (#1278, #1293)."""
    return not local_config.setting("engineBranch") and agent_loop.is_engine_repo(repo)


ENGINE_REFUSAL = "Refused: this is the OliverCode engine repository. Engine changes are the owner's and land on staging."


def _refuse(why: str) -> int:
    print(why if why.startswith("Refused") else f"Refused: {why}")
    return 1


def _claimant(story: dict, now: float) -> str:
    """'claimed by NAME at TIME' for a live claim, else ''; the same rule `log_action --check-claim` applies."""
    lines = "\n".join(json.dumps({"body": c.get("body", "")}) for c in story.get("comments") or [])
    reply = subprocess.CompletedProcess([], 0, lines, "")
    status = log_action.claim_status("", 0, lambda _args: reply, datetime.datetime.fromtimestamp(now, datetime.timezone.utc))
    return "" if status == "free" else status


def _local_claim(slug: str, n: int, now: float, write: str = "", clear: bool = False) -> str:
    """A claim kept in ~/.olivercode while GitHub holds the comment back: 'held by NAME' for one under CLAIM_HOURS old, else ''.
    `write` records a claim for that agent and `clear` drops it."""
    path = gh_budget.home() / "dispatch-claims.json"
    key, limit = f"{slug}#{n}", log_action.CLAIM_HOURS * 3600
    with failure_log.locked(path):  # read, change and write are one step, so two claimers never overwrite each other
        try:
            claims = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            claims = {}
        if clear:
            claims.pop(key, None)
            failure_log.write_private(path, json.dumps(claims))
            return ""
        if write:
            claims = {k: v for k, v in claims.items() if now - float(v.get("at", 0)) < limit}
            claims[key] = {"agent": write, "at": now}
            failure_log.write_private(path, json.dumps(claims))
            return ""
    mine = claims.get(key) or {}
    return f"held by {mine.get('agent')}" if mine and now - float(mine.get("at", 0)) < limit else ""


def live_claim(runner, slug: str, n: int, story: dict, now: float) -> str:
    """'claimed by NAME ...' for a claim another session holds, else ''. A claim expires after CLAIM_HOURS."""
    return _claimant(story, now) or _local_claim(slug, n, now)


def read_story(runner, slug: str, n: int) -> tuple[dict, str]:
    """(story, error) read over REST, which spends no GraphQL points: the issue, then its comments."""
    done = runner(["api", f"repos/{slug}/issues/{n}"])
    if done.returncode != 0:
        return {}, (done.stderr or done.stdout or "gh failed").strip()
    try:
        story = json.loads(done.stdout)
    except ValueError:
        return {}, "GitHub sent an unreadable reply"
    if "pull_request" in story:
        return {}, "it is a pull request"
    comments = runner(["api", f"repos/{slug}/issues/{n}/comments", "--paginate", "--slurp"])
    if comments.returncode != 0:
        return {}, (comments.stderr or comments.stdout or "gh failed").strip()
    try:
        pages = json.loads(comments.stdout or "[]")
    except ValueError:
        return {}, "GitHub sent unreadable comments"
    story["comments"] = [c for page in pages for c in (page if isinstance(page, list) else [page]) if isinstance(c, dict)]
    return story, ""


def _plan(repo) -> int:
    """`dispatch --plan`: print the parallel groups, the models, the stories to rewrite and the long waits (#794)."""
    try:
        cfg = local_config.backlog_config(repo)
        print(intake.render(intake.plan(intake.gh_issues(f"{cfg['repoOwner']}/{cfg['repoName']}"))))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        return _refuse(f"the plan was not built: {exc}")
    return 0


def command_dispatch(argv: list[str], runner=gh, busy=None, clock=None, repo=None, io=None) -> int:
    if argv == ["--plan"]:
        repo = repo or _toplevel()
        return _refuse(ENGINE_REFUSAL) if is_engine(repo) else _plan(repo)
    parsed = _parse(argv)
    if not parsed:
        print(USAGE)
        return 1
    n, sid, dry = parsed
    clock = clock or time.time
    repo = repo or _toplevel()
    if is_engine(repo):
        return _refuse(ENGINE_REFUSAL)
    try:
        cfg = local_config.backlog_config(repo)
        slug = f"{cfg['repoOwner']}/{cfg['repoName']}"
    except (OSError, ValueError, KeyError) as exc:
        return _refuse(f"{repo} has no readable docs/backlog-config.json ({exc}).")
    slug = origin_slug(repo, slug)
    story, why = read_story(runner, slug, n)
    if why:
        return _refuse(f"story #{n} was not read: {why}")
    if story.get("state", "").upper() != "OPEN":
        return _refuse(f"story #{n} is closed.")
    if not intake.files_area(story.get("body") or ""):
        return _refuse(f"story #{n} names no files area, so it is not dispatched. Rewrite it with a `Files area:` line.")
    if wide := intake.folders(intake.files_area(story.get("body") or ""), repo):
        return _refuse(f"story #{n}'s Files area names the folder {wide[0]}, which would hold every other story back. Rewrite it with the files it changes.")
    if _too_large(story):
        return _refuse(f"story #{n} {_too_large(story)}.")
    agent = sid or "dispatch"
    worktree = placement_config().worktrees / f"{repo.name}-{n}"
    if dry:
        refused = _start_checks(runner, slug, n, story, clock, busy)
        if refused:
            return refused
        print(f"Dry run: story #{n} would build headless in {worktree}, claimed as {agent}. No claim posted.")
        return 0
    from lib import cmd_drain  # drain imports this module, so the import waits until a builder runs
    io = io or cmd_drain.Io(Path(repo), slug, agent, runner)
    pid = os.getpid()
    if not cmd_drain.take_run(io, slug, f"dispatch {n}" + (f" from {sid}" if sid else ""), [n]):  # one run per repo: a second thread's story joins the running queue (#992)
        return 0
    try:
        with run_lock.Heartbeat(slug, pid, also=getattr(io, "refresh_claims", None)):
            refused = _start_checks(runner, slug, n, story, clock, busy)
            if refused:
                return refused
            code = _build(io, cmd_drain, story, n, worktree)
            while True:
                queued = run_lock.release(slug, pid)  # stories other threads queued meanwhile run next, in priority order
                if not queued:
                    break
                stories = [st for st, why in (read_story(runner, slug, q) for q in queued) if not why and st.get("state", "").upper() == "OPEN" and not _too_large(st)]
                for nxt in sorted(stories, key=open_issues.rank):
                    if not live_claim(runner, slug, nxt["number"], nxt, clock()):
                        _build(io, cmd_drain, nxt, nxt["number"], placement_config().worktrees / f"{repo.name}-{nxt['number']}")
            return code
    finally:
        run_lock.release(slug, pid)


def _too_large(story: dict) -> str:
    """Why an L or XL story is not built (#1307), or '' when its size allows it."""
    size = intake.size_of(story)
    return f"has Size {size}, so it needs splitting into S and M stories" if size in ("L", "XL") else ""


def _start_checks(runner, slug: str, n: int, story: dict, clock, busy=None) -> int:
    """The refusals before a builder starts: a live claim, or a machine already at its builder limit (#1055). 0 when none applies."""
    claim = live_claim(runner, slug, n, story, clock())
    if claim:
        return _refuse(f"story #{n} is {claim}. Take the next open story.")
    held, limit = (busy or run_lock.building_elsewhere)(slug), local_config.max_builders()
    if held >= limit:
        return _refuse(f"other runs are building {held} stories, which is this machine's limit of {limit} (maxBuilders in olivercode.local.json). Ask again when one lands.")
    return 0


def _build(io, cmd_drain, story: dict, n: int, worktree) -> int:
    io.claim(n)
    io.beat([n])
    closed, _used = cmd_drain.work_story(io, story, cmd_drain.new_state())
    print(f"Story #{n} {'landed and closed' if closed else 'stayed open and is back on Ready; the reason is in its comment'}. Branch story/{n} in {worktree}.")
    return 0 if closed else 1
