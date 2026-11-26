"""Launcher command `drain`: `olivercode drain REPO` works a repo's open stories until none remain (#707).

It lists open stories through REST (epics, claimed and owner-gated stories are skipped), orders them P0 first, starts headless builders up to the builder cap
and never two whose stories name the same files, then drives each one run -> validate -> `olivercode land` -> comment and close on REST. A builder that exits
before its story lands restarts on the same worktree, up to RESTARTS times, then the blocker is commented on the story and drain moves on. `olivercode dispatch N`
builds one story through the same `work_story`. Every outside effect goes through the `Io` object, so tests inject fakes and never touch the machine or GitHub.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from lib import agent_loop, cmd_dispatch, cmd_groom, cmd_land, cmd_owner, failure_log, gh_budget, intake, session_guard, local_config, owner_decisions, policy, run_lock, status_report
from lib.open_issues import Memo, fetch as fetch_open, owner_gated, rank
from lib.cmd_land import command_land
from lib.local_config import BACKLOG_CONFIG, LOCAL_BACKLOG_CONFIG, OC_ROOT, backlog_config, has_backlog_config
from lib.placement import config as placement_config

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))  # the board copy's reader lives beside the backlog skill (#1014)

USAGE = "Usage: olivercode drain REPO [--parallel N]"
RESTARTS = 3
FULL_WAITS = 4  # twenty minutes of five-minute waits for another repo's run to free a builder (#1055)
REWRITE_SECONDS = status_report.REWRITE_MINUTES * 60  # a running drain rewrites the status page at least this often (#990)
EPIC = re.compile(r"work type:\s*epic", re.IGNORECASE)


def skip_reason(issue: dict, repo: Path | None = None) -> str:
    """Why drain does not start an open story now, or '' when it may. Only a Ready story with a board Size and a Files area is built (#1014)."""
    if owner_gated(issue):
        return "it is owner-gated"
    if issue.get("status") != "Ready":
        return f"its board Status is {issue.get('status') or 'empty'}, not Ready"
    if not issue.get("size"):
        return "it has no Size on the board"
    if issue.get("size") in ("L", "XL"):  # a story this size cannot finish in one builder's turn budget, so it is split into thin stories first (#1123)
        return f"it is Size {issue['size']}, so split it into thin stories first"
    area = intake.files_area(issue.get("body") or "")
    if not area:
        return "it names no Files area"
    if wide := intake.folders(area, repo):
        return f"its Files area names the folder {wide[0]}, which would hold every other story back; name the files instead"
    return ""


def is_epic(issue: dict) -> bool:
    names = [str(l.get("name", "") if isinstance(l, dict) else l).lower() for l in issue.get("labels") or []]
    return "epic" in names or bool(EPIC.search(issue.get("body") or ""))


def new_state() -> dict:
    return {"closed": [], "blocked": [], "sessions": 0, "tokens": 0, "restarts": {}, "api_error_streak": 0, "api_error_stop": ""}


_COST_LOCK = threading.Lock()
_API_ERROR_LOCK = threading.Lock()


def costed(session: str, command: str, call):
    """Run call() and log what it spent under the session, so the cost log can tell the drain's own calls apart (#1114)."""
    key = uuid.uuid4().hex
    with _COST_LOCK:  # the drain's worker threads log together, and the pending file is read and written whole
        gh_budget.note_before(key)
    try:
        return call()
    finally:
        with _COST_LOCK:
            gh_budget.note_after(key, session, command)


class Io:
    """Every outside effect of a drain. Tests replace the methods; the defaults use REST, git, the headless loop and `olivercode land`."""

    def __init__(self, repo: Path, slug: str, agent: str = "drain", runner=None, parallel: int | None = None, origin: str = ""):
        self.repo, self.slug, self.agent, self.runner, self.parallel = repo, slug, agent, runner, parallel
        self.origin = origin or f"olivercode drain {repo.name}"  # the command or thread that started the run, shown beside each landing on the status page (#990)
        self.resumed: dict[int, str] = {}  # story number -> the resume note for a branch an earlier session left (#877)
        self.claimed_at: dict[int, float] = {}  # story number -> when its claim comment was last posted, so a long build refreshes it
        self.memo = Memo()  # the pass's comment and blocker reads, each kept until the story changes (#1114)
        self.built_at: dict[int, str] = {}  # story number -> the stamp its current builder started, which bounds the policy asks it can hit (#1058)
        self.said_limit = ""
        self.code_at = self._code_head()  # runner code this run started on (#1116)

    def _code_head(self) -> str:
        done = subprocess.run(["git", "-C", str(OC_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else ""

    def runner_changed(self) -> int | None:
        """Story whose landing changed runner scripts since this run started, or None (#1116)."""
        if not self.code_at:
            return None
        done = subprocess.run(["git", "-C", str(OC_ROOT), "log", f"{self.code_at}..HEAD", "--format=%s", "--", "scripts"], capture_output=True, text=True)
        found = re.findall(r"\(#(\d+)\)", done.stdout) if done.returncode == 0 else []
        return int(found[0]) if found else None

    def gh(self, args: list[str]):
        """`gh` through the runner a caller injected, else the shared one that honors the GitHub hold, with its cost logged under this run (#1114)."""
        if self.runner:
            return self.runner(args)
        return costed(f"drain:{self.slug}", "gh " + " ".join(args), lambda: cmd_dispatch.gh(args))

    def branch(self) -> str:
        """The repo's default branch, which every ancestry and count check reads (#877)."""
        return cmd_dispatch._default_branch(self.repo)

    def validation(self) -> list[str] | None:
        """The repo's own validation command, which a story needs before a builder starts (#1012)."""
        return agent_loop.validation_command(self.repo)

    def list_open(self) -> list[dict] | None:
        """The open stories, each with its board Status and Size attached, or None when either read fails (#1014)."""
        self.memo.forget("blockers")  # a landing may have closed a blocker; a story's comments are kept until it changes
        issues = costed(f"drain:{self.slug}", f"gh api repos/{self.slug}/issues", lambda: fetch_open(self.slug))
        if issues is None:
            return None
        cards = self.board_cards()
        if cards is None:
            return None
        for issue in issues:
            card = cards.get(issue["number"], {})
            issue["status"], issue["size"] = card.get("status") or "", card.get("size") or ""
        return issues

    def board_cards(self) -> dict[int, dict] | None:
        """The board's card for each story number, from the shared board copy groom keeps. None when the board cannot be read, so drain stops
        rather than treat an unread story as Ready (#1014)."""
        import check_board_hygiene
        try:
            items = check_board_hygiene.load_items(backlog_config(self.repo))
        except (Exception, SystemExit):
            return None
        return {(i.get("content") or {}).get("number"): i for i in items}

    def blockers(self, issue: dict) -> list[int]:
        """The numbers of the open stories that block this one, through GitHub's REST dependency link. The list read says how many are open, so a story
        with none costs no call. A read that fails holds nothing back (#1064)."""
        if not (issue.get("issue_dependencies_summary") or {}).get("blocked_by"):
            return []
        return self.memo.get("blockers", issue, lambda: self._blockers(issue)) or []

    def _blockers(self, issue: dict) -> list[int] | None:
        done = self.gh(["api", f"repos/{self.slug}/issues/{issue['number']}/dependencies/blocked_by"])
        try:
            rows = json.loads(done.stdout) if done.returncode == 0 else None
        except ValueError:
            rows = None
        if rows is None:
            return None
        return sorted(r["number"] for r in rows if isinstance(r, dict) and r.get("state") == "open" and "number" in r)

    def claimed(self, issue: dict) -> bool:
        """True when another session holds a live claim."""
        n, now = issue["number"], time.time()
        rows = (self.memo.get("comments", issue, lambda: self._comments(issue)) or []) if issue.get("comments") else []
        story = {"comments": rows}
        return bool(cmd_dispatch.live_claim(self.gh, self.slug, n, story, now))

    def _comments(self, issue: dict) -> list | None:
        done = self.gh(["api", f"repos/{self.slug}/issues/{issue['number']}/comments"])
        try:
            return json.loads(done.stdout) if done.returncode == 0 else None
        except ValueError:
            return None

    def limit(self) -> int:
        """Temporary Claude-account safety cap: one model session at a time."""
        return 1


    def event(self, kind: str, issue: dict | None = None, queue=(), waiting=()) -> str:
        """Rewrite the status page for a run event and publish it to City on the smallest model (#990). A failure here never stops a run."""
        model_name = agent_loop.model_for(cmd_groom.size_of(issue), issue.get("labels")) if issue and kind == "start" else ""
        try:
            return status_report.record(self.slug, kind, issue, origin=self.origin, builders=self.limit(), queue=queue, waiting=waiting, model_name=model_name)
        except Exception:  # the page never stops a run
            return ""

    def capacity(self) -> int:
        """Only one builder may hold a model slot across the local fleet."""
        return max(0, 1 - run_lock.building_elsewhere(self.slug))


    def holders(self) -> list[str]:
        """The other repos whose runs hold the builders (#1111)."""
        return run_lock.holders_elsewhere(self.slug)

    def beat(self, building: list[int]) -> None:
        """Tell the repo's run lock which stories are building now (#992)."""
        run_lock.beat(self.slug, os.getpid(), time.time(), building)

    def worktree(self, n: int) -> Path:
        """Create story/N's worktree from origin's default branch, or reuse the one a restart finds."""
        path = placement_config().worktrees / f"{self.repo.name}-{n}"
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin", self.branch()], capture_output=True, text=True)  # a base older than origin repeats landed work (#1011)
        problems, self.resumed[n] = cmd_land.resume_worktree(self.repo, path, str(n), f"origin/{self.branch()}")
        if problems:
            raise RuntimeError("; ".join(problems))
        return path

    def cancel_requested(self, n: int) -> bool:
        return run_lock.cancel_requested(self.slug, n)

    def clear_cancel(self, n: int) -> bool:
        return run_lock.clear_cancel(self.slug, n)

    def build(self, issue: dict, worktree: Path, note: str) -> dict:
        """One headless builder session on the story: the brief holds the code the story names and the owner's decisions, and the
        model is the one the brief names (#1015), with a small story getting a third round (#890)."""
        n, size = issue["number"], cmd_groom.size_of(issue)
        extras = "".join(part + "\n" for part in (cmd_dispatch.file_excerpts(issue.get("body") or "", worktree), owner_decisions.brief_section(n)) if part)
        brief = cmd_dispatch.headless_brief(n, issue, self.agent, worktree, extras, note=note or self.resumed.get(n, ""))
        builder, _reader, why = intake.models(issue, f"story-{n}")
        files = intake.files_area(issue.get("body") or "")
        review = agent_loop.review_mode(size, issue.get("labels") or (), files, cmd_groom.priority_of(issue))
        self.built_at[n] = failure_log.stamp()
        return agent_loop.run_loop(brief, worktree, f"story-{n}", model_name=builder, why=why, max_turns=intake.turns(size),
                                   rounds=agent_loop.MAX_ROUNDS + (1 if size in intake.SMALL else 0), review_mode=review, repo=self.slug, stop_check=lambda: self.cancel_requested(n))

    def policy_stop(self, n: int, worktree: Path) -> dict | None:
        """The policy ask that stopped story/N's builder in this run, or None (#1058)."""
        return policy_stop_in(worktree.name, self.built_at.get(n, ""))

    def commit_block(self, n: int, worktree: Path) -> dict | None:
        """The commit-msg gate block that answered story/N's builder in this run, or None (#1096)."""
        return commit_block_in(worktree.name, self.built_at.get(n, ""))

    def backlog(self, n: int) -> None:
        """Put story N's card back to Backlog, for a story whose builder the same gate blocked on every restart (#1096)."""
        cfg = backlog_config(self.repo)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "Backlog"}}]}]))

    def queue_owner(self, n: int, stop: dict) -> None:
        """One open owner-queue line for a story a policy ask stopped. A story already waiting on the owner gets no second line (#1058)."""
        key = f"policy-stop:{self.slug}#{n}"
        if any(i["status"] == "open" and i.get("key") == key for i in cmd_owner.items()):
            return
        at = f" at the {stop['gate']} gate" if stop["gate"] else ""
        cmd_owner.add(self.agent, f"Story #{n} waits on you: {stop['rule']} stopped its builder{at}, so drain did not restart it. The story comment names the next action.",
                      extra={"key": key, "story": n, "gate": stop["gate"]})

    def commits(self, worktree: Path) -> int:
        done = subprocess.run(["git", "-C", str(worktree), "rev-list", "--count", f"origin/{self.branch()}..HEAD"], capture_output=True, text=True)
        return int(done.stdout.strip() or 0) if done.returncode == 0 else 0

    def pending(self, n: int) -> bool:
        """True when story/N's worktree already holds commits that origin's default branch lacks, so an older commit naming the story is not its finish (#1011)."""
        path = placement_config().worktrees / f"{self.repo.name}-{n}"
        return path.is_dir() and self.commits(path) > 0

    def landed(self, worktree: Path, n: int) -> bool:
        """True when a commit that names the story is on origin's default branch (#877). It reads the main checkout, so a builder that landed and
        removed its worktree still counts, and it fetches first so a landing made by another process is seen."""
        branch = self.branch()
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin", branch], capture_output=True, text=True)
        ran = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", "--format=%s"], capture_output=True, text=True)
        return ran.returncode == 0 and any(f"(#{n})" in line for line in ran.stdout.splitlines())

    def notes(self, n: int) -> list[str]:
        """The comment bodies on story N, read over REST. [] when the read failed."""
        done = self.gh(["api", f"repos/{self.slug}/issues/{n}/comments"])
        try:
            notes = json.loads(done.stdout) if done.returncode == 0 else []
        except ValueError:
            notes = []
        return [str(note.get("body") or "") for note in notes if isinstance(note, dict)]

    def landed_lead(self, issue: dict) -> tuple[str, str] | None:
        """(sha, subject) of the newest commit on origin's default branch that names the story this one was built with in a batch session
        ("batch session with #M" in its comments) and changed a file in this story's Files area. It answers only for a story with no commit of
        its own, whose close was refused for want of one, so a mate left by a batched build is recognized and is not built again (#988, #1084).
        A commit that merely touched a shared file is not a lead."""
        n, area = issue["number"], intake.files_area(issue.get("body") or "")
        if not area or not issue.get("comments"):
            return None
        notes = self.notes(n)
        mates = {m for note in notes for m in re.findall(r"batch session with #(\d+)", note)}
        if not mates or not any(f"no commit for (#{n})" in note for note in notes):
            return None
        branch = self.branch()
        ran = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", "--name-only", "--format=COMMIT%x09%H%x09%s"],
                             capture_output=True, text=True)
        if ran.returncode != 0:
            return None
        rows: list[tuple[str, str, set[str]]] = []
        for line in ran.stdout.splitlines():
            if line.startswith("COMMIT\t"):
                _, sha, subject = line.split("\t", 2)
                rows.append((sha, subject, set()))
            elif line.strip() and rows:
                rows[-1][2].add(line.strip())
        if any(f"(#{n})" in subject for _, subject, _ in rows):
            return None
        return next(((sha, subject) for sha, subject, files in rows if any(f"(#{m})" in subject for m in mates) and intake.overlaps(sorted(files), area)), None)

    def told(self, n: int, sha: str) -> bool:
        """True when a "Not built" comment on story N already names the commit, so drain says it once (#1084)."""
        return any(note.startswith("Not built: commit " + sha[:12]) for note in self.notes(n))

    def cleanup_landed(self, n: int) -> list[str]:
        """Reconcile the story worktree and its owned branches after its work is already on the default branch."""
        worktree = placement_config().worktrees / f"{self.repo.name}-{n}"
        if not worktree.exists():
            return []
        return cmd_land.cleanup(worktree)

    def land(self, worktree: Path, n: int) -> tuple[bool, str]:
        out = subprocess.run([sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "land", str(worktree), str(n)], capture_output=True, text=True,
                             env={**os.environ, cmd_land.LAND_AS: self.agent})  # the land skips the wait on a claim this run holds (#1106)
        return out.returncode == 0, (out.stdout + out.stderr).strip()[-300:]

    def comment(self, n: int, body: str) -> None:
        self.gh(["api", "-X", "POST", f"repos/{self.slug}/issues/{n}/comments", "-f", f"body={body}"])

    def close_by_script(self, worktree: Path, n: int, why: str) -> tuple[bool, str]:
        """Log the builder entry for the commit that names the story on origin's default branch, then close the story through complete_story.py
        with the landing's output as its Run output (#912). Returns (closed, the refusal when the close was not made)."""
        branch = self.branch()
        log = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", "--format=%H%x09%s"], capture_output=True, text=True)
        sha = next((line.split("\t")[0] for line in log.stdout.splitlines() if f"(#{n})" in line), "")
        if not sha:
            return False, f"no commit for (#{n}) is on origin/{branch}"
        files = subprocess.run(["git", "-C", str(self.repo), "diff-tree", "--no-commit-id", "--name-only", "-r", sha], capture_output=True, text=True).stdout.split()
        config = self.repo / (LOCAL_BACKLOG_CONFIG if (self.repo / LOCAL_BACKLOG_CONFIG).is_file() else BACKLOG_CONFIG)
        scripts = OC_ROOT / "skills" / "backlog" / "scripts"
        logged = subprocess.run([sys.executable, str(scripts / "log_action.py"), "--config", str(config), "--story", str(n), "--agent", self.agent,
                                 "--role", "builder", "--commit", sha, "--files", str(len(files)), "--result", f"landed from {worktree.name}"],
                                capture_output=True, text=True, cwd=self.repo)
        if logged.returncode != 0:
            return False, (logged.stdout + logged.stderr).strip()[-500:]
        evidence = f"Landed by {self.agent} from {worktree.name} on branch story/{n}.\n\nRun output:\n{why or 'pushed'}"
        done = subprocess.run([sys.executable, str(scripts / "complete_story.py"), "--story", str(n), "--config", str(config), "--evidence", evidence],
                              capture_output=True, text=True, cwd=self.repo)
        if done.returncode == 0:
            return True, ""
        return False, (done.stdout + done.stderr).strip()[-500:]

    def keep_open(self, n: int, reason: str = "") -> None:
        """After a builder that did not land: say why on the story, reopen it when something closed it, and put its card back to Ready (#877)."""
        if reason:
            self.comment(n, f"Builder stopped without landing: {reason}")
        done = self.gh(["api", f"repos/{self.slug}/issues/{n}", "--jq", ".state"])
        if done.returncode == 0 and done.stdout.strip() == "closed":
            self.gh(["api", "-X", "PATCH", f"repos/{self.slug}/issues/{n}", "-f", "state=open"])
        cfg = backlog_config(self.repo)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "Ready"}}]}]))

    def ready(self, n: int) -> None:
        """Put the card of a story a dead run left In Progress back to Ready (#1201)."""
        cfg = backlog_config(self.repo)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "Ready"}}]}]))

    def refresh_claims(self, now: float | None = None) -> None:
        """While this run is alive, renew each claim it holds: the local claim every call, and the claim comment once a quarter of the
        claim window has passed. A run that dies stops renewing, so its claim expires (#1033)."""
        now = now or time.time()
        for n, posted in list(self.claimed_at.items()):
            cmd_dispatch._local_claim(self.slug, n, now, write=self.agent)
            if now - posted < cmd_dispatch.log_action.CLAIM_HOURS * 900 or gh_budget.refusal() or gh_budget.reserve_write():
                continue
            body = cmd_dispatch.log_action.build_claim(self.agent, cmd_dispatch.datetime.datetime.fromtimestamp(now, cmd_dispatch.datetime.timezone.utc))
            cmd_dispatch.log_action.post_comment(self.slug, n, body, lambda args: self.gh(["api", *args]))
            self.claimed_at[n] = now

    def release(self, n: int) -> None:
        """Drop the local claim and post the release comment, so no outcome leaves the story held (#877)."""
        self.claimed_at.pop(n, None)
        run_lock.finish_story(self.slug, os.getpid(), n)
        cmd_dispatch._local_claim(self.slug, n, time.time(), clear=True)
        if gh_budget.refusal() or gh_budget.reserve_write():
            return
        stamp = cmd_dispatch.datetime.datetime.now(cmd_dispatch.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            cmd_dispatch.log_action.post_comment(self.slug, n, f"Claim released\n- Session: {self.agent}\n- Reason: builder finished\n- Time: {stamp}",
                                                 lambda args: self.gh(["api", *args]))
        except RuntimeError:
            pass

    def claim(self, n: int) -> None:
        """Write the claim, locally and as a comment, before the builder starts. While the GitHub budget is held, the comment waits and the card's move to In Progress is queued."""
        now = time.time()
        cmd_dispatch._local_claim(self.slug, n, now, write=self.agent)
        self.claimed_at[n] = now
        if gh_budget.refusal() or gh_budget.reserve_write():
            cfg = backlog_config(self.repo)
            cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "In Progress"}}]}]))
            return
        body = cmd_dispatch.log_action.build_claim(self.agent, cmd_dispatch.datetime.datetime.fromtimestamp(now, cmd_dispatch.datetime.timezone.utc))
        try:
            cmd_dispatch.log_action.post_comment(self.slug, n, body, lambda args: self.gh(["api", *args]))
        except RuntimeError:
            pass


class CloseRefused(RuntimeError):
    """complete_story.py refused the close of a landed story. The story stays open with the gate's message on it (#912)."""


def land_and_close(io, worktree: Path, n: int) -> tuple[bool, str]:
    """The sequence after a passing builder: land the worktree's new commits, or accept an earlier landing when the worktree has none, then close
    through complete_story.py with no model call. New commits land first, so an older commit on main that names the story never stands in for them (#1011).
    Returns (landed, why or the blocker). A refused close comments the gate's message on the story and raises CloseRefused (#912)."""
    if io.commits(worktree) > 0:
        ok, why = io.land(worktree, n)
        if not ok and "rebase-conflict" in why:  # another story landed on the same lines first, which sharing files allows (#1080)
            return False, ("Landing hit a rebase conflict with work that landed meanwhile. In the worktree, run git fetch and git rebase onto origin's "
                           "default branch, keep both changes where they conflict, run the story's tests, commit and stop.")
        if not ok:
            return False, f"Landing failed: {why}"
        if not io.landed(worktree, n):  # the story closes only on a commit that origin's default branch holds (#877)
            return False, f"Landing reported success but no commit for (#{n}) is on the default branch: {why}"
    elif io.landed(worktree, n):
        why = "already on the default branch"
    else:
        return False, "The builder finished with no commit on the branch."
    closed, reason = io.close_by_script(worktree, n, why)
    if not closed:
        io.comment(n, f"Close refused by complete_story.py: {reason}")
        raise CloseRefused(reason)
    return True, why


def _event(io, kind: str, issue: dict | None = None, **info) -> str:
    """Tell the io a run event happened, when it keeps a status page. A test's fake io has no `event`, so nothing happens there."""
    hook = getattr(io, "event", None)
    return hook(kind, issue, **info) if hook else ""


def work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    """Drive one story to landed, restarting its builder on the same worktree. Returns (closed, tokens used here). A story that did not land is left open on Ready, and the claim is released on every exit. Each builder takes one story, so no commit carries two stories' work (#988)."""
    n = issue["number"]
    try:
        closed, used = _work_story(io, issue, state)
        if not closed and n not in state.get("cancelled", []):
            io.keep_open(n)  # a story that did not land stays open with its card in Ready (#877)
        _event(io, "land" if closed else "held", issue)
        return closed, used
    except CloseRefused:  # a landed story whose close the gate refused stays where it is, with the gate's message on it (#1011)
        _event(io, "held", issue)
        return False, 0
    except CommitBlocked as blocked:  # the same gate blocked each restart, or the turn limit stopped it twice, so the story waits in Backlog for the owner (#1096, #1123)
        io.backlog(n)
        _event(io, "held", issue)
        return False, blocked.tokens
    finally:
        for cleanup in (lambda: io.release(n), lambda: io.clear_cancel(n)):
            try:
                cleanup()
            except Exception:
                pass


def budget_handoff(worktree: Path, out: dict) -> str:
    """What a builder that used every turn left: the commits and changed files on its branch (done) and its last words (left), so the next round resumes from them (#1113)."""
    def git(*args):
        done = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else ""
    commits, changed = git("log", "--format=%h %s", "@{upstream}..HEAD") or git("log", "-5", "--format=%h %s"), git("status", "--short")
    return (f"Done: {commits or 'no commits yet'}" + (f"\nUncommitted: {changed}" if changed else "")
            + f"\nLeft: {(out.get('summary') or '').strip()[:600] or 'finish the story and commit it'}")


def held_comment(worktree: Path, finding: str) -> str:
    """The one comment a held story gets: that nothing was pushed, where the branch is kept, and the finding itself (#975)."""
    return f"Held by the fresh reader, so nothing was pushed. The branch is kept in {worktree} and the story goes back to Ready.\n\nFinding:\n{finding[:2000]}"


def policy_stop_in(repo: str, start: str) -> dict | None:
    """The policy ask that answered a commit of `repo` since `start`, as {'rule', 'gate', 'finding', 'file'}, or None. The hooks log the ask
    as a policy line, and the commit-gate block that repeated most in the same window is the gate, its newest line the finding (#1058)."""
    if not start:
        return None
    rows = failure_log.since(repo, start)
    asks = [reason for _, _, gate, reason in rows if gate == "policy" and reason.startswith("ask ")]
    if not asks:
        return None
    blocks = [(gate, reason) for _, _, gate, reason in rows if gate not in policy.NON_COMMIT_GATES]
    gate, finding = "", ""
    if blocks:
        gate = Counter(g for g, _ in blocks).most_common(1)[0][0]
        finding = next(reason for g, reason in reversed(blocks) if g == gate)
    named = re.search(r"[\w.-]+(?:/[\w.-]+)*\.\w+", finding)
    return {"rule": asks[-1][len("ask "):], "gate": gate, "finding": finding, "file": named.group(0) if named else ""}


def commit_block_in(repo: str, start: str) -> dict | None:
    """The newest commit-msg gate block of `repo` since `start`, as {'gate', 'reason'} with the gate's message verbatim, or None. The hook logs
    a block under its own name and the message starts with the gate's [commit-msg] tag (#1096)."""
    if not start:
        return None
    rows = [reason for _, _, _, reason in failure_log.since(repo, start) if reason.startswith("[commit-msg] BLOCKED")]
    return {"gate": "commit-msg", "reason": rows[-1]} if rows else None


class CommitBlocked(Exception):
    """The commit-msg gate blocked every round of a story's builder, so it goes back to Backlog (#1096)."""
    def __init__(self, tokens: int):
        self.tokens = tokens


class TurnLimitParked(CommitBlocked):
    """A builder stopped on the turn limit twice in a row, so the story is parked in Backlog (#1123)."""


class SpendCeilingParked(CommitBlocked):
    """A story exceeded its cumulative spend ceiling and must not start another builder round (#1218)."""


TURN_LIMIT_STOPS = 2  # consecutive stops on the turn limit after which the story is parked instead of restarted


def commit_block_note(block: dict) -> str:
    """What the next round's brief says about the last block: the gate's reason verbatim and the ask to rewrite the message (#1096)."""
    return f"the {block['gate']} gate blocked the commit: {block['reason']}\nRewrite the commit message to pass that gate, then commit again."


def policy_stop_comment(stop: dict) -> str:
    """The one comment a policy-stopped story gets: the rule and gate, the last finding, the file it named and the one next action (#1058)."""
    return (f"Stopped by the policy, so drain starts no restart: {stop['rule']} answered this builder's commit with ask, and a headless session cannot answer it.\n"
            f"- Gate: {stop['gate'] or 'none'}\n"
            f"- Last finding: {stop['finding'] or 'none'}\n"
            f"- File: {stop['file'] or 'none named'}\n"
            "- Next: run the diagnosing-bugs loop on the gate's finding, then return this story to Ready.")


def story_spend(n: int, repo: str = "") -> float:
    """Recorded spend for a story, across model sessions and legacy rows."""
    return session_guard.story_spend(n, repo)


def story_cost_unknown(n: int, repo: str = "") -> bool:
    """Whether the story has an unpriced or incomplete prior model invocation."""
    return session_guard.story_cost_unknown(n, repo)


def _work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    n, tokens, note, blocks, budget_stops = issue["number"], 0, "", 0, 0
    lead = io.landed_lead(issue)
    if lead:  # the work landed under another story, so a fresh build would repeat it on main; the owner decides (#988)
        if not io.told(n, lead[0]):
            io.comment(n, f"Not built: commit {lead[0][:12]} ({lead[1]}) is the batch session commit that changed this story's files, so its work most likely landed under that story. The owner decides whether this story closes.")
        return False, 0
    if not io.pending(n) and io.landed(io.repo, n):  # its commit is on the default branch and no unlanded work waits in its worktree, so it closes through the script and no builder starts (#1011)
        closed, reason = io.close_by_script(io.repo, n, "already on the default branch")
        if not closed:
            io.comment(n, f"Close refused by complete_story.py: {reason}")
            raise CloseRefused(reason)
        cleanup = getattr(io, "cleanup_landed", None)
        if cleanup:
            for line in cleanup(n):
                if line.startswith("Kept ") or " stays:" in line:
                    io.comment(n, f"Cleanup incomplete after landing: {line}")
        return True, 0
    if io.validation() is None:  # no builder starts in a repo that nothing can validate (#1012)
        io.comment(n, f"Drain blocked: {agent_loop.NO_VALIDATION}")
        return False, 0
    try:
        worktree = io.worktree(n)
    except RuntimeError as exc:
        io.comment(n, f"Drain blocked: the worktree was not created: {exc}")
        return False, 0
    attempt, story_api_errors = 0, 0
    while attempt <= RESTARTS:
        session_attempts = session_guard.story_attempts(n, getattr(io, "slug", ""))
        max_attempts = local_config.max_story_attempts()
        if session_attempts >= max_attempts:
            io.comment(n, f"Parked: this story has reached its {max_attempts}-session attempt ceiling across runs and handoffs; no further model session will start.\n"
                          "- Next: split the work or review the prior attempts, then raise maxStoryAttempts in olivercode.local.json and return it to Ready.")
            raise CommitBlocked(tokens)
        ceiling, spent = local_config.max_story_spend(), story_spend(n, getattr(io, "slug", ""))
        unknown = story_cost_unknown(n, getattr(io, "slug", ""))
        if unknown or spent >= ceiling:
            detail = "a prior session's cost is unknown" if unknown else f"it has spent ${spent:.2f}, reaching its ${ceiling:.2f} ceiling"
            io.comment(n, f"Parked: {detail}; no further model session will start.\n"
                          "- Next: reconcile the cost, split the work, or raise maxStorySpend in olivercode.local.json and return the story to Ready.")
            raise SpendCeilingParked(tokens)
        if state.get("api_error_stop"):
            return False, tokens
        state["sessions"] += 1
        state["restarts"][n] = attempt
        out = io.build(issue, worktree, note)
        tokens += out.get("tokens", 0)
        if out.get("done") and io.cancel_requested(n):
            out = {**out, "cancelled": True, "summary": out.get("summary") or out.get("reason") or ""}
        if out.get("cancelled"):
            handoff = budget_handoff(worktree, out)
            io.backlog(n)
            state.setdefault("cancelled", []).append(n)
            io.comment(n, f"Cancelled by the owner before landing. The worktree and branch are kept for a handoff; nothing was pushed.\\n- Next: review the handoff and return the story to Ready when you want to resume.\\n{handoff}")
            return False, tokens
        if out.get("api_error"):
            story_api_errors += 1
            cause = str(out.get("api_error_cause") or out.get("reason") or "Unspecified API error")[:300]
            with _API_ERROR_LOCK:
                state["api_error_streak"] = state.get("api_error_streak", 0) + 1
                streak = state["api_error_streak"]
                if streak >= 5:
                    state["api_error_stop"] = cause
            if streak >= 5:
                io.comment(n, f"Drain stopped after five consecutive API errors across the queue. Last cause: {cause}")
                return False, tokens
            delay = min(60 * (2 ** (story_api_errors - 1)), 900)
            io.comment(n, f"Claude API error; retrying this story in {delay} seconds (attempt {story_api_errors}). Cause: {cause}")
            time.sleep(delay)
            continue
        with _API_ERROR_LOCK:
            state["api_error_streak"] = 0
        attempt += 1
        if out.get("held"):  # a reader's finding that a fix did not clear holds the story, so the builder is not restarted (#975)
            io.comment(n, held_comment(worktree, out["held"]))
            return False, tokens
        if out.get("fatal"):  # a reason a restart cannot fix blocks the story and starts no new session (#1012)
            io.comment(n, f"Drain blocked: {out['reason']}")
            return False, tokens
        if out["done"]:
            try:
                closed, note = land_and_close(io, worktree, n)
            except CloseRefused:
                return False, tokens
            if closed:
                return True, tokens
        elif out.get("budget"):  # a spent budget leaves a handoff on the story, and the next round starts from it (#1113)
            budget_stops += 1
            note = budget_handoff(worktree, out)
            if budget_stops >= TURN_LIMIT_STOPS:  # the same story spent every turn twice running, so a third restart would loop; park it (#1123)
                io.comment(n, f"Parked: the builder stopped on the turn limit {budget_stops} times in a row, so drain starts no restart, releases the claim and moves the story to Backlog.\n"
                              f"- Next: split the story into thin stories, or rewrite it smaller, then return it to Ready.\n{note}")
                raise TurnLimitParked(tokens)
            io.comment(n, f"Budget reached: the builder used every turn, and the next round resumes from this handoff.\n{note}")
        else:
            note, budget_stops = out["reason"], 0
        stop = io.policy_stop(n, worktree)
        if stop:  # a policy ask answers a headless builder with no one to answer it, so a restart would hit the same ask (#1058)
            io.comment(n, policy_stop_comment(stop))
            io.queue_owner(n, stop)
            return False, tokens
        block = getattr(io, "commit_block", lambda *_: None)(n, worktree)  # shortcut: fakes without the method read as no block, drop when every Io has it
        if block:  # the next round is told why the commit was blocked and asked to rewrite the message (#1096)
            note, blocks = commit_block_note(block), blocks + 1
        else:
            blocks = 0
    if blocks > RESTARTS:
        io.comment(n, f"Drain blocked: the {block['gate']} gate blocked the builder's commit on all {RESTARTS + 1} rounds, so the story is back in Backlog and its claim is released. Reason: {block['reason']}")
        raise CommitBlocked(tokens)
    io.comment(n, f"Drain blocked after {RESTARTS} restarts of the builder on {worktree}. Last reason: {note}")
    return False, tokens


def stop_builders(io, running: dict) -> None:
    """Put each story this run was building back on Ready and release its claim, so a stopped run strands no claim (#1076). Each effect is tried on its own."""
    for issue in running.values():
        n = issue["number"]
        for effect in (lambda: io.keep_open(n, "drain was stopped before the builder landed"), lambda: io.release(n)):
            try:
                effect()
            except Exception:
                pass


def _stop_on_term(signum, frame):
    """SIGTERM ends a run the same way Ctrl-C does, so the run releases its claims and lock on the way out (#1076)."""
    raise KeyboardInterrupt


def drain(io, state: dict, sleep=time.sleep, say=print) -> int:
    """Run the loop until no story is left to start. Returns 0 when it ended, 1 when GitHub could not be read. A stop (Ctrl-C or SIGTERM) releases
    the claims of the stories it was building and returns to Ready without waiting for their builders (#1076)."""
    running: dict = {}
    pool = ThreadPoolExecutor(max_workers=max(1, io.limit()))
    waits, reported, begun = 0, set(), False
    stopped = False
    issues = None  # read once, and again only after a story lands or fails (#1114)
    try:
        while True:
            issues = issues if issues is not None else io.list_open()
            if issues is None:
                say("Drain stopped: the open stories were not read.")
                return 1
            skip = set(state["closed"]) | set(state["blocked"]) | {i["number"] for i in running.values()}
            todo = []
            for issue in sorted((i for i in issues if i["number"] not in skip and not is_epic(i)), key=rank):
                if why := skip_reason(issue, io.repo):  # each skipped story is named once per drain, with the reason (#1014)
                    if issue["number"] not in reported:
                        reported.add(issue["number"])
                        say(f"Skipped #{issue['number']}: {why}.")
                    continue
                if held := io.blockers(issue):  # a story waits until every blocker is closed, and the skip names the blocker (#1064)
                    if (issue["number"], tuple(held)) not in reported:
                        reported.add((issue["number"], tuple(held)))
                        say(f"Skipped #{issue['number']}: it is blocked by open {', '.join(f'#{b}' for b in held)}.")
                    continue
                todo.append(issue)
            if note := getattr(io, "limit_note", lambda: "")():
                say(note)
            waiting = [i for i in issues if owner_gated(i) and not is_epic(i)]
            if not begun and todo:
                begun = True
                message = _event(io, "begin", queue=todo, waiting=waiting)
                if message:
                    say(message)
            started = False
            paused = run_lock.is_paused(io.slug)
            for issue in ([] if paused or state.get("restart") or state.get("api_error_stop") else todo):
                with run_lock.claim_guard(io.slug) as allowed:
                    if not allowed:
                        paused = True
                        break
                    if len(running) >= io.capacity():
                        break
                    area = intake.files_area(issue.get("body") or "")
                    if any(intake.overlaps(area, intake.files_area(active.get("body") or "")) for active in running.values()):
                        marker = (issue["number"], "shared-files")
                        if marker not in reported:
                            reported.add(marker)
                            say(f"Skipped #{issue['number']}: its Files area overlaps a story already building.")
                        continue
                    if io.claimed(issue):
                        continue
                    io.claim(issue["number"])
                    running[pool.submit(work_story, io, issue, state)] = issue
                    started = True
                _event(io, "start", issue, queue=[t for t in todo if t is not issue and t not in running.values()], waiting=waiting)
            run_lock.set_paused(io.slug, os.getpid(), paused)
            if paused and "paused" not in reported:
                say("Runner paused. Existing builders are finishing; no new story will start. Run olivercode resume REPO to continue.")
                reported.add("paused")
            if not paused:
                reported.discard("paused")
            io.beat([i["number"] for i in running.values()])
            if not running:
                if state.get("restart") or state.get("api_error_stop"):
                    break
                if paused:
                    sleep(2)
                    issues = None
                    continue
                if todo and not started and waits < FULL_WAITS and io.capacity() == 0:
                    waits += 1
                    sleep(300)
                    issues = None  # other runs may have landed or closed stories while this one waited
                    continue
                if todo and not started and io.capacity() == 0:
                    say(f"Stopping after {FULL_WAITS * 5} minutes: every builder is held by {', '.join(io.holders()) or 'another run'}.")
                break
            finished, _ = wait(running, timeout=REWRITE_SECONDS, return_when=FIRST_COMPLETED)
            if not finished:
                _event(io, "tick")  # nothing landed in the interval, so the page still gets its rewrite (#990)
                continue
            for fut in finished:
                issue = running.pop(fut)
                try:
                    closed, used = fut.result()
                except Exception as exc:  # one crashed worker blocks its own story and the run goes on (#1011)
                    closed, used = False, 0
                    n = issue["number"]
                    say(f"Story #{n} crashed: {exc!r}")
                    for effect in (lambda: io.comment(n, f"Drain blocked: the worker crashed with {exc!r}."), lambda: io.keep_open(n), lambda: io.release(n)):
                        try:
                            effect()
                        except Exception:
                            pass
                state["tokens"] += used
                issues = None
                (state["closed"] if closed else state["blocked"]).append(issue["number"])
                if closed and not state.get("restart") and (moved := getattr(io, "runner_changed", lambda: None)()):
                    state["restart"] = moved
            io.beat([i["number"] for i in running.values()])
    except BaseException:  # Ctrl-C or SIGTERM (#1076): the stories in flight go back to Ready and their claims go, then the stop goes on
        stopped = True
        stop_builders(io, running)
        say(f"Drain stopped: {len(running)} building stories released to Ready. Their builders are not waited for.")
        raise
    finally:
        pool.shutdown(wait=not stopped)
        if begun:
            _event(io, "end")
    if state.get("api_error_stop"):
        say(f"Drain stopped after five consecutive API errors. Last cause: {state['api_error_stop']}")
        return 1
    if state.get("restart"):
        say(f"Drain restarting on the new code: #{state['restart']} changed the runner.")
        return 0
    say(f"Drain done: {len(state['closed'])} stories closed, {len(state['blocked'])} blocked, {state['sessions']} sessions, {state['tokens']:,} tokens.")
    return 0


def resolve_repo(name: str) -> Path | None:
    """A path, or a repo folder beside OliverCode, with a readable backlog config."""
    for path in (Path(name).expanduser(), OC_ROOT.parent / name):
        if has_backlog_config(path):
            return path.resolve()
    return None


def status_page() -> str:
    """The page the run lock names for watching a run: the status digest."""
    try:
        from lib import cmd_status
        return str(cmd_status.digest_path())
    except Exception:  # noqa: BLE001 -- a missing page never stops a run
        return ""


def local_claims(slug: str) -> list[int]:
    """The story numbers of `slug` that hold a local claim. Only a runner writes one, so when a run takes the repo's lock, each is a claim its
    process left behind (#1076)."""
    try:
        claims = json.loads((gh_budget.home() / "dispatch-claims.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    prefix = f"{slug}#"
    return sorted(int(key[len(prefix):]) for key in claims if key.startswith(prefix) and key[len(prefix):].isdigit())


def take_run(io, slug: str, who: str, want: list[int] | None = None, say=print) -> bool:
    """Take the repo's run lock, or join the run that holds it (#992). True when this process now holds the run. When another run is live, `want` is
    appended to its queue, the holder is named and nothing starts. A dead holder's lock is taken over, its claims are released and the queue resumes from the board."""
    now = time.time()
    held, taken, why = run_lock.acquire(slug, who, now, page=status_page(), want=want)
    if held:
        join = (f"Story #{want[0]} joins its queue." if want else "It reads the board each pass, so every open story joins its queue in priority order.")
        say(f"No second run starts for {slug}: {run_lock.describe(held, now)} {join}")
        return False
    if taken:
        say(f"Took over the run lock for {slug} from {taken.get('who')}, because {why}. The queue resumes from the board.")
    stale = sorted(set(taken.get("building") or []) | set(local_claims(slug)))  # no live run holds the repo, so every claim it left is stale (#1076)
    if stale:
        say(f"Released the claims no run holds: {', '.join(f'#{n}' for n in stale)}.")
    for n in stale:
        io.release(n)
    for n in taken.get("building") or []:  # only a story the dead run was building goes back to Ready (#1201)
        io.ready(n)
    return True


def command_drain(argv: list[str], io_factory=Io, sleep=time.sleep, exit_now=os._exit, restart=os.execv) -> int:
    """`drain REPO` runs up to the machine-wide builder limit, or exactly N with `--parallel N` (#1055). One run holds a repo at a time (#992)."""
    args, parallel, rest = list(argv), None, []
    while args:
        arg = args.pop(0)
        if arg == "--parallel":
            if not args or not args[0].isdigit() or int(args[0]) < 1:
                print(USAGE)
                return 2
            parallel = int(args.pop(0))
        else:
            rest.append(arg)
    if len(rest) != 1 or rest[0].startswith("-"):
        print(USAGE)
        return 2
    repo = resolve_repo(rest[0])
    if repo is None:
        print(f"Refused: {rest[0]} is not a repo with docs/backlog-config.json.")
        return 1
    cfg = backlog_config(repo)
    slug = cmd_dispatch.origin_slug(repo, f"{cfg['repoOwner']}/{cfg['repoName']}")  # a fork reads its own origin, as dispatch does (#1012)
    io, pid = io_factory(repo, slug, parallel=parallel), os.getpid()
    if hasattr(io, "origin"):
        io.origin = " ".join(["olivercode drain", *argv])
    on_main = threading.current_thread() is threading.main_thread()  # signal handlers can only be set on the main thread (#1076)
    # A terminal closing its tab sends SIGHUP; treat it like SIGTERM so
    # in-flight claims and the run lock are released through the same path.
    previous = {sig: signal.signal(sig, _stop_on_term) for sig in (signal.SIGTERM, signal.SIGHUP)} if on_main else {}
    code, state = 0, {}
    try:
        if not take_run(io, slug, f"drain {repo.name}"):
            return 0
        state = new_state()
        with run_lock.Heartbeat(slug, pid, also=getattr(io, "refresh_claims", None)):
            code = drain(io, state, sleep=sleep)
            while code == 0 and not state.get("restart") and run_lock.release(slug, pid):  # a story another thread queued as this run ended is worked before the lock goes
                code = drain(io, state, sleep=sleep)
    except KeyboardInterrupt:  # drain has released its claims and said so; the lock goes in the finally below (#1076)
        code = 130
    finally:
        run_lock.release(slug, pid)
        if on_main:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    if code == 0 and state.get("restart"):
        sys.stdout.flush()
        restart(sys.executable, [sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "drain", *argv])
    if code == 130:  # builder threads would hold the exit until their sessions end, so a stopped run ends the process here (#1076)
        sys.stdout.flush()
        sys.stderr.flush()
        exit_now(130)
    return code
