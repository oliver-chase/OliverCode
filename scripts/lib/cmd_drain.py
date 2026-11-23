"""Launcher command `drain`: `olivercode drain REPO` works a repo's open stories until none remain (#707).

It lists open stories through REST (epics, claimed and owner-gated stories are skipped), orders them P0 first, starts headless builders up to the builder cap
and never two whose stories name the same files, then drives each one run -> validate -> `olivercode land` -> comment and close on REST. A builder that exits
before its story lands restarts on the same worktree, up to RESTARTS times, then the blocker is commented on the story and drain moves on. `olivercode dispatch N`
builds one story through the same `work_story`. Every outside effect goes through the `Io` object, so tests inject fakes and never touch the machine or GitHub.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from lib import agent_loop, cmd_dispatch, cmd_groom, cmd_land, gh_budget, intake, owner_decisions
from lib.open_issues import fetch as fetch_open, owner_gated, rank
from lib.cmd_land import command_land
from lib.local_config import BACKLOG_CONFIG, LOCAL_BACKLOG_CONFIG, OC_ROOT, backlog_config, has_backlog_config
from lib.placement import config as placement_config

USAGE = "Usage: olivercode drain REPO [--parallel N]"
RESTARTS = 3
PARALLEL = 1  # builders one drain runs at once; more only when the owner asks with --parallel N (#979)
LOAD_WAITS = 12
FILE_TOKEN = re.compile(r"`([\w./-]+\.\w+|[\w.-]+/[\w./-]*)`")
EPIC = re.compile(r"work type:\s*epic", re.IGNORECASE)
FILES_AREA = re.compile(r"files area:\s*(.+)", re.IGNORECASE)


def story_files(issue: dict) -> set[str]:
    """The paths a story names in backticks, which decide whether two stories can run side by side."""
    return {m.rstrip("/") for m in FILE_TOKEN.findall(issue.get("body") or "")}


def files_area(issue: dict) -> set[str]:
    """The paths on a story's Files area line, bare or in backticks, for the check that finds a mate's work already on main (#988)."""
    return {part.strip(" `.").rstrip("/") for line in FILES_AREA.findall(issue.get("body") or "") for part in line.split(",") if part.strip(" `.")}


def is_epic(issue: dict) -> bool:
    names = [str(l.get("name", "") if isinstance(l, dict) else l).lower() for l in issue.get("labels") or []]
    return "epic" in names or bool(EPIC.search(issue.get("body") or ""))


def new_state() -> dict:
    return {"closed": [], "blocked": [], "sessions": 0, "tokens": 0, "restarts": {}}


class Io:
    """Every outside effect of a drain. Tests replace the methods; the defaults use REST, git, the headless loop and `olivercode land`."""

    def __init__(self, repo: Path, slug: str, agent: str = "drain", runner=None, parallel: int = PARALLEL):
        self.repo, self.slug, self.agent, self.runner, self.parallel = repo, slug, agent, runner, parallel
        self.resumed: dict[int, str] = {}  # story number -> the resume note for a branch an earlier session left (#877)

    def gh(self, args: list[str]):
        """`gh` through the runner a caller injected, else the shared one that honors the GitHub hold."""
        return (self.runner or cmd_dispatch.gh)(args)

    def branch(self) -> str:
        """The repo's default branch, which every ancestry and count check reads (#877)."""
        return cmd_dispatch._default_branch(self.repo)

    def list_open(self) -> list[dict] | None:
        return fetch_open(self.slug)

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

    def capacity(self) -> int:
        return self.parallel

    def load_ok(self) -> bool:
        return cmd_dispatch.machine_load()[0] > 0

    def worktree(self, n: int) -> Path:
        """Create story/N's worktree from origin's default branch, or reuse the one a restart finds."""
        path = placement_config().worktrees / f"{self.repo.name}-{n}"
        problems, self.resumed[n] = cmd_land.resume_worktree(self.repo, path, str(n), f"origin/{self.branch()}")
        if problems:
            raise RuntimeError("; ".join(problems))
        return path

    def build(self, issue: dict, worktree: Path, note: str) -> dict:
        """One headless builder session on the story: the brief holds the code the story names and the owner's decisions, and the
        model follows the story size, with a small story getting a third round on the next model up (#890)."""
        n, size = issue["number"], cmd_groom.size_of(issue)
        extras = "".join(part + "\n" for part in (cmd_dispatch.file_excerpts(issue.get("body") or "", worktree), owner_decisions.brief_section(n)) if part)
        brief = cmd_dispatch.headless_brief(n, issue, self.agent, worktree, extras, note=note or self.resumed.get(n, ""))
        return agent_loop.run_loop(brief, worktree, f"story-{n}", model_name=agent_loop.model_for(size, issue.get("labels")), size=size,
                                   rounds=agent_loop.MAX_ROUNDS + (1 if size in intake.SMALL else 0))

    def commits(self, worktree: Path) -> int:
        done = subprocess.run(["git", "-C", str(worktree), "rev-list", "--count", f"origin/{self.branch()}..HEAD"], capture_output=True, text=True)
        return int(done.stdout.strip() or 0) if done.returncode == 0 else 0

    def landed(self, worktree: Path, n: int) -> bool:
        """True when a commit that names the story is on origin's default branch (#877). It reads the main checkout, so a builder that landed and
        removed its worktree still counts, and it fetches first so a landing made by another process is seen."""
        branch = self.branch()
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin", branch], capture_output=True, text=True)
        ran = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", "--format=%s"], capture_output=True, text=True)
        return ran.returncode == 0 and any(f"(#{n})" in line for line in ran.stdout.splitlines())

    def landed_lead(self, issue: dict) -> tuple[str, str] | None:
        """(sha, subject) of the newest commit on origin's default branch that names another story and changed a file in this story's Files area.
        It answers only for a story with no commit of its own, whose close was refused for want of one, so a mate left by a batched build is
        recognized and is not built again (#988)."""
        n, area = issue["number"], files_area(issue)
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
        lead = next(((sha, subject) for sha, subject, files in rows if files & area and re.search(r"\(#\d+\)", subject)), None)
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
        out = subprocess.run([sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "land", str(worktree), str(n)], capture_output=True, text=True)
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

    def release(self, n: int) -> None:
        """Drop the local claim and post the release comment, so no outcome leaves the story held (#877)."""
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
    """The sequence after a passing builder: land (or accept an earlier landing), then close through complete_story.py with no model call.
    Returns (landed, why or the blocker). A refused close comments the gate's message on the story and raises CloseRefused (#912)."""
    if io.landed(worktree, n):
        why = "already on the default branch"
    elif io.commits(worktree) == 0:
        return False, "The builder finished with no commit on the branch."
    else:
        ok, why = io.land(worktree, n)
        if not ok:
            return False, f"Landing failed: {why}"
        if not io.landed(worktree, n):  # the story closes only on a commit that origin's default branch holds (#877)
            return False, f"Landing reported success but no commit for (#{n}) is on the default branch: {why}"
    closed, reason = io.close_by_script(worktree, n, why)
    if not closed:
        io.comment(n, f"Close refused by complete_story.py: {reason}")
        raise CloseRefused(reason)
    return True, why


def work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    """Drive one story to landed, restarting its builder on the same worktree. Returns (closed, tokens used here). A story that did not land is left open on Ready, and the claim is released on every exit. Each builder takes one story, so no commit carries two stories' work (#988)."""
    n = issue["number"]
    try:
        closed, used = _work_story(io, issue, state)
        if not closed:
            io.keep_open(n)  # a story that did not land stays open with its card in Ready (#877)
        return closed, used
    finally:
        io.release(n)


def held_comment(worktree: Path, finding: str) -> str:
    """The one comment a held story gets: that nothing was pushed, where the branch is kept, and the finding itself (#975)."""
    return f"Held by the fresh reader, so nothing was pushed. The branch is kept in {worktree} and the story goes back to Ready.\n\nFinding:\n{finding[:2000]}"


def _work_story(io, issue: dict, state: dict) -> tuple[bool, int]:
    n, tokens, note = issue["number"], 0, ""
    lead = io.landed_lead(issue)
    if lead:  # the work landed under another story, so a fresh build would repeat it on main; the owner decides (#988)
        io.comment(n, f"Not built: commit {lead[0][:12]} ({lead[1]}) on the default branch changed this story's files, so its work most likely landed under that story. The owner decides whether this story closes.")
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
        if not out["done"]:
            note = out["reason"]
            continue
        try:
            closed, note = land_and_close(io, worktree, n)
        except CloseRefused:
            return False, tokens
        if closed:
            return True, tokens
    io.comment(n, f"Drain blocked after {RESTARTS} restarts of the builder on {worktree}. Last reason: {note}")
    return False, tokens


def drain(io, state: dict, sleep=time.sleep, say=print) -> int:
    """Run the loop until no story is left to start. Returns 0 when it ended, 1 when GitHub could not be read."""
    running: dict = {}
    pool = ThreadPoolExecutor(max_workers=max(1, io.capacity()))
    waits = 0
    try:
        while True:
            issues = io.list_open()
            if issues is None:
                say("Drain stopped: the open stories were not read.")
                return 1
            skip = set(state["closed"]) | set(state["blocked"]) | {i["number"] for i in running.values()}
            todo = sorted((i for i in issues if i["number"] not in skip and not is_epic(i) and not owner_gated(i)), key=rank)
            busy = set().union(*(story_files(i) for i in running.values())) if running else set()
            started = False
            for issue in todo:
                if len(running) >= io.capacity():
                    break
                files = story_files(issue)
                if files & busy or io.claimed(issue):
                    continue
                if not io.load_ok():
                    break
                io.claim(issue["number"])
                running[pool.submit(work_story, io, issue, state)] = issue
                busy |= files
                started = True
            if not running:
                if todo and not started and waits < LOAD_WAITS and not io.load_ok():
                    waits += 1
                    sleep(300)
                    continue
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in finished:
                issue = running.pop(fut)
                closed, used = fut.result()
                state["tokens"] += used
                (state["closed"] if closed else state["blocked"]).append(issue["number"])
    finally:
        pool.shutdown(wait=True)
    say(f"Drain done: {len(state['closed'])} stories closed, {len(state['blocked'])} blocked, {state['sessions']} sessions, {state['tokens']:,} tokens.")
    return 0


def resolve_repo(name: str) -> Path | None:
    """A path, or a repo folder beside OliverCode, with a readable backlog config."""
    for path in (Path(name).expanduser(), OC_ROOT.parent / name):
        if has_backlog_config(path):
            return path.resolve()
    return None


def command_drain(argv: list[str], io_factory=Io, sleep=time.sleep) -> int:
    """`drain REPO`, one story at a time, or `drain REPO --parallel N` for up to N builders at once (#979)."""
    args, parallel, rest = list(argv), PARALLEL, []
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
    slug = f"{cfg['repoOwner']}/{cfg['repoName']}"
    return drain(io_factory(repo, slug, parallel=parallel), new_state(), sleep=sleep)
