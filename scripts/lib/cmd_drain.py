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
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from lib import agent_loop, cmd_dispatch, cmd_groom, cmd_land, cmd_owner, failure_log, gh_budget, gitfiles, intake, local_config, model, policy, run_lock
from lib.open_issues import fetch as fetch_open, owner_gated, rank
from lib.cmd_land import command_land
from lib.local_config import BACKLOG_CONFIG, LOCAL_BACKLOG_CONFIG, OC_ROOT, backlog_config, has_backlog_config
from lib.placement import config as placement_config

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))  # the board copy's reader lives beside the backlog skill (#1014)

USAGE = "Usage: olivercode drain REPO [--parallel N] [--foreground]"
RESTARTS = 3
HOLD_WAIT_MAX = 3600  # a GitHub hold that ends within this many seconds is waited out instead of ending the run (#1314)
FULL_WAITS = 12 # five-minute waits for another repo's run to free a builder before a full machine ends the drain (#1055)
EPIC = re.compile(r"work type:\s*epic", re.IGNORECASE)


def notify(text: str) -> None:
    """One macOS notification for the owner. A missing osascript, or the suite's guard standing in for it, sends nothing and the run goes on (#1308)."""
    script = f'display notification "{text.replace(chr(92), "").replace(chr(34), chr(39))}" with title "OliverCode drain"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


NO_AREA = "it names no Files area"


def skip_reason(issue: dict, repo: Path | None = None) -> str:
    """Why drain does not start an open story now, or '' when it may. Only a Ready story with a board Size and a Files area is built (#1014)."""
    if owner_gated(issue):
        return "it is owner-gated"
    if issue.get("status") != "Ready":
        return f"its board Status is {issue.get('status') or 'empty'}, not Ready"
    if not issue.get("size"):
        return "it has no Size on the board"
    if str(issue["size"]).strip().upper() in ("L", "XL"):
        return f"its Size is {issue['size']}, so it needs splitting into S and M stories"
    area = intake.files_area(issue.get("body") or "")
    if not area:
        return NO_AREA
    if wide := intake.folders(area, repo):
        return f"its Files area names the folder {wide[0]}, which would hold every other story back; name the files instead"
    return ""


def is_epic(issue: dict) -> bool:
    names = [str(l.get("name", "") if isinstance(l, dict) else l).lower() for l in issue.get("labels") or []]
    return "epic" in names or bool(EPIC.search(issue.get("body") or ""))


def new_state() -> dict:
    return {"closed": [], "blocked": [], "sessions": 0, "tokens": 0, "restarts": {}}


class Io:
    """Every outside effect of a drain. Tests replace the methods; the defaults use REST, git, the headless loop and `olivercode land`."""

    def __init__(self, repo: Path, slug: str, agent: str = "drain", runner=None, parallel: int | None = None):
        self.repo, self.slug, self.agent, self.runner, self.parallel = repo, slug, agent, runner, parallel
        self.resumed: dict[int, str] = {}  # story number -> the resume note for a branch an earlier session left (#877)
        self.claim_start: dict[int, float] = {}  # story number -> when this run claimed it, never refreshed (#1306)
        self.claimed_at: dict[int, float] = {}  # story number -> when its claim comment was last posted, so a long build refreshes it
        self.said: dict[int, str] = {}  # story number -> its last comment, which is the reason a stopped row records (#1291)
        self.built_at: dict[int, str] = {}  # story number -> the stamp its current builder started, which bounds the policy asks it can hit (#1058)

    def gh(self, args: list[str]):
        """`gh` through the runner a caller injected, else the shared one that honors the GitHub hold."""
        return (self.runner or cmd_dispatch.gh)(args)

    def branch(self) -> str:
        """The repo's default branch, which every ancestry and count check reads (#877)."""
        return agent_loop.default_branch(self.repo)

    def validation(self) -> list[str] | None:
        """The repo's own validation command, which a story needs before a builder starts (#1012)."""
        return agent_loop.validation_command(self.repo)

    def list_open(self) -> list[dict] | None:
        """The open stories, each with its board Status and Size attached, or None when either read fails (#1014)."""
        issues = fetch_open(self.slug)
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
        self.unread = ""
        try:
            items = check_board_hygiene.load_items(backlog_config(self.repo))
        except SystemExit as stop:  # the REST read could not finish, and the drain says so (#1310)
            self.unread = str(stop.code or "")
            return None
        except Exception:
            return None
        return {(i.get("content") or {}).get("number"): i for i in items}

    def add_files_area(self, issue: dict) -> bool:
        """Give a Ready story with no Files area one, once, just before it builds (#1316). One call to the smallest model reads the story and the repo's
        tracked files and names the files it changes. Every named file must be tracked or on a Creates line, else the story stays unchanged.
        On success the story's body gets a `Files area:` line, a comment names the files, and `issue['body']` is updated for this run."""
        body, n = issue.get("body") or "", issue["number"]
        tracked = gitfiles.tracked_files(self.repo)
        prompt = (f"Story #{n}: {issue.get('title', '')}\n\n{body}\n\nThe repo's tracked files:\n" + "\n".join(tracked) +
                  "\n\nName the files this story changes. Reply with one line only, `Files area: ` then the paths, comma-separated. Name files, never folders. Reply `Files area:` with none when you cannot tell.")  # shortcut: the whole file list goes in the prompt, so a repo too large for it finds none; split by folder when one does
        try:
            ran = model.run_cli(prompt, str(self.repo), allowed_tools="", max_turns=1, timeout=120, model=agent_loop.LADDER[0])
        except model.ModelError:
            return False
        named = intake.files_area(ran["text"]) if ran["code"] == 0 else []
        made = set(intake.creates(body))
        if not named or any(p not in tracked and p not in made for p in named):
            return False
        line = "Files area: " + ", ".join(named)
        done = self.gh(["api", "-X", "PATCH", f"repos/{self.slug}/issues/{n}", "-f", f"body={body.rstrip()}\n\n{line}\n"])
        if done.returncode != 0:
            return False
        issue["body"] = f"{body.rstrip()}\n\n{line}\n"
        self.comment(n, f"The drain added this story's {line}")
        return True

    def blockers(self, issue: dict) -> list[int]:
        """The numbers of the open stories that block this one, through GitHub's REST dependency link. The list read says how many are open, so a story
        with none costs no call. A read that fails holds nothing back (#1064)."""
        if not (issue.get("issue_dependencies_summary") or {}).get("blocked_by"):
            return []
        done = self.gh(["api", f"repos/{self.slug}/issues/{issue['number']}/dependencies/blocked_by"])
        try:
            rows = json.loads(done.stdout) if done.returncode == 0 else []
        except ValueError:
            rows = []
        return sorted(r["number"] for r in rows if isinstance(r, dict) and r.get("state") == "open" and "number" in r)

    def claimed(self, issue: dict) -> bool:
        """True when another session holds a live claim."""
        n, now = issue["number"], time.time()
        rows: list = []
        if issue.get("comments"):
            done = self.gh(["api", f"repos/{self.slug}/issues/{n}/comments"])
            try:
                rows = json.loads(done.stdout) if done.returncode == 0 else []
            except ValueError:
                rows = []
        story = {"comments": rows}
        return bool(cmd_dispatch.live_claim(self.gh, self.slug, n, story, now))

    def limit(self) -> int:
        """The most builders this run may hold: --parallel N, else the machine-wide limit (#1055)."""
        return self.parallel or local_config.max_builders()

    def capacity(self) -> int:
        """Builders this run may hold now: --parallel N, else the machine limit less what other repos' runs are building."""
        return self.parallel or max(0, local_config.max_builders() - run_lock.building_elsewhere(self.slug))

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

    def build(self, issue: dict, worktree: Path, note: str) -> dict:
        """One headless builder session on the story: the brief holds the code the story names, and the
        model is the one the brief names (#1015), with a small story getting a third round (#890)."""
        n, size = issue["number"], cmd_groom.size_of(issue)
        extras = "".join(part + "\n" for part in (cmd_dispatch.file_excerpts(issue.get("body") or "", worktree)) if part)
        brief = cmd_dispatch.headless_brief(n, issue, self.agent, worktree, extras, note=note or self.resumed.get(n, ""))
        builder, _reader, why = intake.models(issue, f"story-{n}")
        files = intake.files_area(issue.get("body") or "")
        review = agent_loop.review_mode(size, issue.get("labels") or (), files, cmd_groom.priority_of(issue))
        self.built_at[n] = failure_log.stamp()
        agent_loop.log_stage(f"story-{n}", self.repo.name, "building")
        return agent_loop.run_loop(brief, worktree, f"story-{n}", model_name=builder, why=why,
                                   rounds=agent_loop.MAX_ROUNDS + (1 if size in intake.SMALL else 0), review_mode=review, repo=self.repo.name)

    def policy_stop(self, n: int, worktree: Path) -> dict | None:
        """The policy ask that stopped story/N's builder in this run, or None (#1058)."""
        return policy_stop_in(worktree.name, self.built_at.get(n, ""))

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

    def since_claim(self, n: int) -> list[str]:
        """The git log filter that keeps only commits made after the drain claimed story n, so an older commit that names it never stands in for
        the claim's own work (#1306). A story with no claim in this run is not filtered."""
        return [f"--since={int(self.claim_start[n])}"] if n in self.claim_start else []

    def landed(self, worktree: Path, n: int) -> bool:
        """True when a commit made after this claim that names the story is on origin's default branch (#877, #1306). It reads the main checkout, so a builder that landed and
        removed its worktree still counts, and it fetches first so a landing made by another process is seen."""
        branch = self.branch()
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin", branch], capture_output=True, text=True)
        ran = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", *self.since_claim(n), "--format=%s"], capture_output=True, text=True)
        return ran.returncode == 0 and any(f"(#{n})" in line for line in ran.stdout.splitlines())

    def landed_lead(self, issue: dict) -> tuple[str, str] | None:
        """(sha, subject) of the newest commit on origin's default branch that names another story and changed a file in this story's Files area.
        It answers only for a story with no commit of its own, whose close was refused for want of one, so a mate left by a batched build is
        recognized and is not built again (#988)."""
        n, area = issue["number"], intake.files_area(issue.get("body") or "")
        if not area:
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
        lead = next(((sha, subject) for sha, subject, files in rows if intake.overlaps(sorted(files), area) and re.search(r"\(#\d+\)", subject)), None)
        if lead is None or not issue.get("comments"):
            return None
        done = self.gh(["api", f"repos/{self.slug}/issues/{n}/comments"])
        try:
            notes = json.loads(done.stdout) if done.returncode == 0 else []
        except ValueError:
            notes = []
        refused = any(f"no commit for (#{n})" in str(note.get("body") or "") for note in notes if isinstance(note, dict))
        return lead if refused else None

    def land(self, worktree: Path, n: int) -> tuple[bool, str]:
        agent_loop.log_stage(f"story-{n}", self.repo.name, "landing")
        out = subprocess.run([sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "land", str(worktree), str(n)], capture_output=True, text=True)
        if out.returncode == 0:
            self.claim_start.pop(n, None)  # land keeps a lone older commit's committer date, so a resumed branch's commit would fail the since-claim filter (#1306)
        return out.returncode == 0, (out.stdout + out.stderr).strip()[-300:]

    def comment(self, n: int, body: str) -> None:
        self.said[n] = body
        self.gh(["api", "-X", "POST", f"repos/{self.slug}/issues/{n}/comments", "-f", f"body={body}"])

    def close_by_script(self, worktree: Path, n: int, why: str) -> tuple[bool, str]:
        """Log the builder entry for the commit that names the story on origin's default branch, then close the story through complete_story.py
        with the landing's output as its Run output (#912). Returns (closed, the refusal when the close was not made)."""
        branch = self.branch()
        log = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", *self.since_claim(n), "--format=%H%x09%s"], capture_output=True, text=True)
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
            agent_loop.log_stage(f"story-{n}", self.repo.name, "landed")
            return True, ""
        return False, (done.stdout + done.stderr).strip()[-500:]

    def staged(self) -> bool:
        """True when this repo is OliverCode's own and lands on the owner's engineBranch, where complete_story.py refuses a close by design (#1297)."""
        return bool(agent_loop.setting("engineBranch")) and agent_loop.is_engine_repo(self.repo)

    def park_in_qa(self, n: int) -> None:
        """An engine story that landed on the engine branch waits in QA with its issue open: a comment names the commit, the card moves, and the run log says landed (#1297)."""
        branch = self.branch()
        log = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", "--format=%H%x09%s"], capture_output=True, text=True)
        sha = next((line.split("\t")[0] for line in log.stdout.splitlines() if f"(#{n})" in line), "")
        self.comment(n, f"Landed on {branch} in commit {sha[:12] or 'unknown'}. The story stays open in QA until the owner promotes it.")
        cfg = backlog_config(self.repo)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": "QA"}}]}]))
        agent_loop.log_stage(f"story-{n}", self.repo.name, "landed")

    def stopped(self, n: int, reason: str) -> None:
        """Append the stopped row that says why a story left the status line (#1291)."""
        agent_loop.log_stage(f"story-{n}", self.repo.name, "stopped", reason=reason)

    def keep_open(self, n: int, reason: str = "") -> None:
        """After a builder that did not land: say why on the story, reopen it when something closed it, and put its card back to Ready (#877)."""
        self.stopped(n, reason or self.said.get(n, ""))
        if reason:
            self.comment(n, f"Builder stopped without landing: {reason}")
        done = self.gh(["api", f"repos/{self.slug}/issues/{n}", "--jq", ".state"])
        if done.returncode == 0 and done.stdout.strip() == "closed":
            self.gh(["api", "-X", "PATCH", f"repos/{self.slug}/issues/{n}", "-f", "state=open"])
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
        cmd_dispatch._local_claim(self.slug, n, time.time(), clear=True)
        if gh_budget.refusal() or gh_budget.reserve_write():
            return
        stamp = cmd_dispatch.datetime.datetime.now(cmd_dispatch.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            cmd_dispatch.log_action.post_comment(self.slug, n, f"Claim released\n- Session: {self.agent}\n- Reason: builder finished\n- Time: {stamp}",
                                                 lambda args: self.gh(["api", *args]))
        except RuntimeError:
            pass

    def claim(self, n: int, size: str = "") -> None:
        """Write the claim, locally and as a comment, before the builder starts. While the GitHub budget is held, the comment waits and the card's move to In Progress is queued."""
        now = time.time()
        cmd_dispatch._local_claim(self.slug, n, now, write=self.agent)
        self.claimed_at[n] = self.claim_start[n] = now
        if size:
            agent_loop.STORY_SIZE[f"story-{n}"] = size
        agent_loop.log_stage(f"story-{n}", self.repo.name, "claimed")
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


class Parked(RuntimeError):
    """An engine story landed on the engine branch and waits in QA, so nothing more is done for it (#1297)."""


def land_and_close(io, worktree: Path, n: int) -> tuple[bool, str]:
    """The sequence after a passing builder: land the worktree's new commits, or accept an earlier landing when the worktree has none, then close
    through complete_story.py with no model call. New commits land first, so an older commit on main that names the story never stands in for them (#1011).
    Returns (landed, why or the blocker). A refused close comments the gate's message on the story and raises CloseRefused (#912)."""
    if io.commits(worktree) > 0:
        ok, why = io.land(worktree, n)
        if not ok:
            return False, f"Landing failed: {why}"
        if not io.landed(worktree, n):  # the story closes only on a commit that origin's default branch holds (#877)
            return False, f"Landing reported success but no commit for (#{n}) is on the default branch: {why}"
    elif io.landed(worktree, n):
        why = "already on the default branch"
    else:
        return False, "The builder finished with no commit on the branch."
    finish(io, worktree, n, why)
    return True, why


def finish(io, worktree: Path, n: int, why: str) -> None:
    """Close a landed story through complete_story.py. An engine story on the engine branch parks in QA instead and raises Parked (#1297).
    A refused close comments the gate's message, logs its one stopped row and raises CloseRefused (#912, #1291)."""
    if io.staged():
        io.park_in_qa(n)
        raise Parked(n)
    closed, reason = io.close_by_script(worktree, n, why)
    if not closed:
        io.comment(n, f"Close refused by complete_story.py: {reason}")
        io.stopped(n, reason)  # the refusal is the reason status shows (#1291)
        notify(f"Story #{n} close refused: {reason}")
        raise CloseRefused(reason)


def work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    """Drive one story to landed, restarting its builder on the same worktree. Returns (closed, tokens used here). A story that did not land is left open on Ready, and the claim is released on every exit. Each builder takes one story, so no commit carries two stories' work (#988)."""
    n = issue["number"]
    try:
        closed, used = _work_story(io, issue, state)
        if not closed:
            io.keep_open(n)  # a story that did not land stays open with its card in Ready (#877)
        return closed, used
    except (CloseRefused, Parked):  # a refused close leaves the story with the gate's message and its one stopped row (#1011); a parked one waits in QA (#1297)
        return False, 0
    finally:
        io.release(n)


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


def policy_stop_comment(stop: dict) -> str:
    """The one comment a policy-stopped story gets: the rule and gate, the last finding, the file it named and the one next action (#1058)."""
    return (f"Stopped by the policy, so drain starts no restart: {stop['rule']} answered this builder's commit with ask, and a headless session cannot answer it.\n"
            f"- Gate: {stop['gate'] or 'none'}\n"
            f"- Last finding: {stop['finding'] or 'none'}\n"
            f"- File: {stop['file'] or 'none named'}\n"
            "- Next: run the diagnosing-bugs loop on the gate's finding, then return this story to Ready.")


def _work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    n, tokens, note = issue["number"], 0, ""
    lead = io.landed_lead(issue)
    if lead:  # the work landed under another story, so a fresh build would repeat it on main; the owner decides (#988)
        io.comment(n, f"Not built: commit {lead[0][:12]} ({lead[1]}) on the default branch changed this story's files, so its work most likely landed under that story. The owner decides whether this story closes.")
        return False, 0
    if not io.pending(n) and io.landed(io.repo, n):  # its commit is on the default branch and no unlanded work waits in its worktree, so it closes through the script and no builder starts (#1011)
        finish(io, io.repo, n, "already on the default branch")
        return True, 0
    if io.validation() is None:  # no builder starts in a repo that nothing can validate (#1012)
        io.comment(n, f"Drain blocked: {agent_loop.NO_VALIDATION}")
        return False, 0
    try:
        worktree = io.worktree(n)
    except RuntimeError as exc:
        io.comment(n, f"Drain blocked: the worktree was not created: {exc}")
        return False, 0
    for attempt in range(RESTARTS + 1):
        state["sessions"] += 1
        state["restarts"][n] = attempt
        out = io.build(issue, worktree, note)
        tokens += out.get("tokens", 0)
        if out.get("held"):  # a reader's finding that a fix did not clear holds the story, so the builder is not restarted (#975)
            io.comment(n, held_comment(worktree, out["held"]))
            return False, tokens
        if out.get("usage_limit"):  # the story goes back to Ready unblocked, and the drain starts no new builder (#1299)
            state.setdefault("limited", []).append(n)
            io.comment(n, f"Drain stopped: {out['reason']}")
            notify(f"Story #{n} hit the usage limit: {out['reason']}")
            return False, tokens
        if out.get("fatal"):  # a reason a restart cannot fix blocks the story and starts no new session (#1012)
            io.comment(n, f"Drain blocked: {out['reason']}")
            return False, tokens
        if out["done"]:
            try:
                closed, note = land_and_close(io, worktree, n)
            except (CloseRefused, Parked):  # work_story ends the story and logs no second row (#1297), so the tokens are counted here
                state["tokens"] += tokens
                raise
            if closed:
                return True, tokens
            if "push-failed" in note:  # a refused push is not the builder's to fix, so no session is restarted for it (#1296)
                io.comment(n, f"Drain blocked: {note}")
                return False, tokens
        else:
            note = out["reason"]
        stop = io.policy_stop(n, worktree)
        if stop:  # a policy ask answers a headless builder with no one to answer it, so a restart would hit the same ask (#1058)
            io.comment(n, policy_stop_comment(stop))
            io.queue_owner(n, stop)
            return False, tokens
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
    waits, reported, filled = 0, set(), set()
    stopped = False
    hold_waited = False

    def reap(finished) -> None:
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
            if closed or issue["number"] not in state.get("limited", ()):  # a story released at the usage limit is not a failed round (#1299)
                (state["closed"] if closed else state["blocked"]).append(issue["number"])
        io.beat([i["number"] for i in running.values()])

    try:
        while True:
            until = gh_budget.blocked_until()
            if until and until - time.time() <= HOLD_WAIT_MAX:  # a hold that ends within the hour is waited out, once (#1314)
                if running:  # builders finish first, and their board writes are already queued by the hold
                    reap(wait(running, return_when=FIRST_COMPLETED)[0])
                    continue
                reset = time.strftime("%H:%M", time.localtime(until))
                if hold_waited:
                    state["held"] = f"GitHub's rate-limit hold was still on after the reset it named, about {reset}"
                    agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "stopped", reason=state["held"])
                    say(f"Drain stopped: {state['held']}.")
                    return 1
                hold_waited = True
                agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "waiting", reason=f"GitHub's rate-limit hold lasts until about {reset}")
                say(f"Waiting for GitHub's rate-limit reset at about {reset}.")
                sleep(max(0.0, until - time.time()) + 1)
                gh_budget.replay()  # the writes queued during the hold go first
                continue
            hold_waited = False
            issues = io.list_open()
            if issues is None:
                if unread := getattr(io, "unread", ""):
                    agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "stopped", reason=unread)
                    say(f"Drain stopped: {unread}.")
                    return 1
                say("Drain stopped: the open stories were not read.")
                return 1
            skip = set(state["closed"]) | set(state["blocked"]) | {i["number"] for i in running.values()}
            todo = []
            for issue in sorted((i for i in issues if i["number"] not in skip and not is_epic(i)), key=rank):
                why = skip_reason(issue, io.repo)
                if why == NO_AREA and issue["number"] not in filled:  # a Ready story gets its Files area once per drain, just before it builds (#1316)
                    filled.add(issue["number"])
                    if io.add_files_area(issue):
                        why = skip_reason(issue, io.repo)
                    else:
                        why += " and none could be found"
                if why:  # each skipped story is named once per drain, with the reason (#1014)
                    if issue["number"] not in reported:
                        reported.add(issue["number"])
                        say(f"Skipped #{issue['number']}: {why}.")
                        if owner_gated(issue):
                            notify(f"Story #{issue['number']} is owner-gated and waits for you")
                    continue
                if held := io.blockers(issue):  # a story waits until every blocker is closed, and the skip names the blocker (#1064)
                    if (issue["number"], tuple(held)) not in reported:
                        reported.add((issue["number"], tuple(held)))
                        say(f"Skipped #{issue['number']}: it is blocked by open {', '.join(f'#{b}' for b in held)}.")
                    continue
                todo.append(issue)
            busy = [intake.files_area(i.get("body") or "") for i in running.values()]  # one overlap rule, shared with the planner (#1014)
            started = False
            for issue in todo:
                if state.get("limited") or len(running) >= io.capacity():  # no builder starts once one has hit the usage limit (#1299)
                    break
                areas = intake.files_area(issue.get("body") or "")
                if any(intake.overlaps(areas, b) for b in busy) or io.claimed(issue):
                    continue
                io.claim(issue["number"], issue.get("size") or "")
                running[pool.submit(work_story, io, issue, state)] = issue
                busy.append(areas)
                started = True
            io.beat([i["number"] for i in running.values()])
            if not running:
                if todo and not started and waits < FULL_WAITS and io.capacity() == 0 and not state.get("limited"):
                    waits += 1
                    sleep(300)
                    continue
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            reap(finished)
    except BaseException:  # Ctrl-C or SIGTERM (#1076): the stories in flight go back to Ready and their claims go, then the stop goes on
        stopped = True
        stop_builders(io, running)
        say(f"Drain stopped: {len(running)} building stories released to Ready. Their builders are not waited for.")
        raise
    finally:
        pool.shutdown(wait=not stopped)
    if state.get("limited"):
        say(f"Drain stopped for the usage limit: {agent_loop.USAGE_LIMIT_REASON}, so no new builder started.")
    say(f"Drain done: {len(state['closed'])} stories closed, {len(state['blocked'])} blocked, {state['sessions']} sessions, {state['tokens']:,} tokens.")
    return 0


def resolve_repo(name: str) -> Path | None:
    """A path, or a repo folder under repoRoot or beside OliverCode, with a readable backlog config (#1298)."""
    for path in (Path(name).expanduser(), placement_config().root / name, OC_ROOT.parent / name):
        if has_backlog_config(path):
            return path.resolve()
    return None


def status_page() -> str:
    """The page the run lock names for watching a run: the status digest until the status page lands (#990)."""
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
    return True


def slug_of(repo: Path) -> str:
    cfg = backlog_config(repo)
    return cmd_dispatch.origin_slug(repo, f"{cfg['repoOwner']}/{cfg['repoName']}")  # a fork reads its own origin, as dispatch does (#1012)


def detach(argv: list[str], repo: Path, spawn=subprocess.Popen) -> int:
    """Start this drain again as its own session with its output in a log, so it outlives the chat or terminal that started it (#1276)."""
    log = failure_log.home() / "logs"
    log.mkdir(mode=0o700, exist_ok=True)
    with open(log / f"drain-{repo.name}.log", "a", encoding="utf-8") as out:
        spawn([sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "drain", *argv, "--foreground"], stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    print(f"Drain started for {repo.name} in its own process. Log: {out.name}. Follow it with `olivercode watch {repo.name}`.")
    return 0


def command_drain(argv: list[str], io_factory=Io, sleep=time.sleep, exit_now=os._exit, spawn=subprocess.Popen) -> int:
    """`drain REPO` runs up to the machine-wide builder limit, or exactly N with `--parallel N` (#1055), detached unless `--foreground` is given (#1276).
    One run holds a repo at a time (#992). When the run ends it logs one run-end row with the stories it landed and stopped."""
    args, parallel, rest, foreground = list(argv), None, [], False
    while args:
        arg = args.pop(0)
        if arg == "--foreground":
            foreground = True
        elif arg == "--parallel":
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
    if cmd_dispatch.is_engine(repo):
        print(cmd_dispatch.ENGINE_REFUSAL)
        return 1
    if not foreground:
        return detach(argv, repo, spawn)
    slug = slug_of(repo)
    io, pid = io_factory(repo, slug, parallel=parallel), os.getpid()
    on_main = threading.current_thread() is threading.main_thread()  # signal handlers can only be set on the main thread (#1076)
    previous = signal.signal(signal.SIGTERM, _stop_on_term) if on_main else None
    code, state, ran = 0, new_state(), False
    try:
        if not take_run(io, slug, f"drain {repo.name}"):
            return 0
        ran = True
        with run_lock.Heartbeat(slug, pid, also=getattr(io, "refresh_claims", None)):
            code = drain(io, state, sleep=sleep)
            while code == 0 and run_lock.release(slug, pid):  # a story another thread queued as this run ended is worked before the lock goes
                code = drain(io, state, sleep=sleep)
    except KeyboardInterrupt:  # drain has released its claims and said so; the lock goes in the finally below (#1076)
        code = 130
    finally:
        run_lock.release(slug, pid)
        if ran:
            agent_loop.log_stage(f"run-{repo.name}", repo.name, "run-end", landed=len(state["closed"]), stopped=len(state["blocked"]),
                                **({"reason": f"The run stopped for the usage limit: {agent_loop.USAGE_LIMIT_REASON}."} if state.get("limited")
                                   else {"reason": f"The run stopped: {state['held']}."} if state.get("held") else {}))
            try:
                from lib import cmd_status
                cmd_status.write_digest(slug, out=lambda _text: None)  # the digest is current when a run ends (#1313)
            except Exception as exc:  # noqa: BLE001 -- a digest bug never hides the run's end
                print(f"drain: status digest failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
            notify(f"Drain ended: {len(state['closed'])} landed, {len(state['blocked'])} stopped")
        if on_main:
            signal.signal(signal.SIGTERM, previous)
    if code == 130:  # builder threads would hold the exit until their sessions end, so a stopped run ends the process here (#1076)
        sys.stdout.flush()
        sys.stderr.flush()
        exit_now(130)
    return code
