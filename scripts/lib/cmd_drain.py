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
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from lib import agent_loop, cmd_dispatch, cmd_groom, cmd_land, cmd_owner, failure_log, gh_budget, intake, local_config, owner_decisions, policy, run_lock
from lib.open_issues import fetch as fetch_open, owner_gated, rank
from lib.cmd_land import command_land
from lib.local_config import BACKLOG_CONFIG, LOCAL_BACKLOG_CONFIG, OC_ROOT, backlog_config, has_backlog_config
from lib.placement import config as placement_config

sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))  # the board copy's reader lives beside the backlog skill (#1014)

USAGE = "Usage: olivercode drain REPO [--parallel N]"
RESTARTS = 3
FULL_WAITS = 12  # five-minute waits for another repo's run to free a builder before a full machine ends the drain (#1055)
EPIC = re.compile(r"work type:\s*epic", re.IGNORECASE)


def skip_reason(issue: dict) -> str:
    """Why drain does not start an open story now, or '' when it may. Only a Ready story with a board Size and a Files area is built (#1014)."""
    if owner_gated(issue):
        return "it is owner-gated"
    if issue.get("status") != "Ready":
        return f"its board Status is {issue.get('status') or 'empty'}, not Ready"
    if not issue.get("size"):
        return "it has no Size on the board"
    if not intake.files_area(issue.get("body") or ""):
        return "it names no Files area"
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
        self.built_at: dict[int, str] = {}  # story number -> the stamp its current builder started, which bounds the policy asks it can hit (#1058)

    def gh(self, args: list[str]):
        """`gh` through the runner a caller injected, else the shared one that honors the GitHub hold."""
        return (self.runner or cmd_dispatch.gh)(args)

    def branch(self) -> str:
        """The repo's default branch, which every ancestry and count check reads (#877)."""
        return cmd_dispatch._default_branch(self.repo)

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
        try:
            items = check_board_hygiene.load_items(backlog_config(self.repo))
        except (Exception, SystemExit):
            return None
        return {(i.get("content") or {}).get("number"): i for i in items}

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
        """One headless builder session on the story: the brief holds the code the story names and the owner's decisions, and the
        model is the one the brief names (#1015), with a small story getting a third round (#890)."""
        n, size = issue["number"], cmd_groom.size_of(issue)
        extras = "".join(part + "\n" for part in (cmd_dispatch.file_excerpts(issue.get("body") or "", worktree), owner_decisions.brief_section(n)) if part)
        brief = cmd_dispatch.headless_brief(n, issue, self.agent, worktree, extras, note=note or self.resumed.get(n, ""))
        builder, _reader, why = intake.models(issue, f"story-{n}")
        self.built_at[n] = failure_log.stamp()
        return agent_loop.run_loop(brief, worktree, f"story-{n}", model_name=builder, why=why,
                                   rounds=agent_loop.MAX_ROUNDS + (1 if size in intake.SMALL else 0))

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
    except CloseRefused:  # a landed story whose close the gate refused stays where it is, with the gate's message on it (#1011)
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
        closed, reason = io.close_by_script(io.repo, n, "already on the default branch")
        if not closed:
            io.comment(n, f"Close refused by complete_story.py: {reason}")
            raise CloseRefused(reason)
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
        else:
            note = out["reason"]
        stop = io.policy_stop(n, worktree)
        if stop:  # a policy ask answers a headless builder with no one to answer it, so a restart would hit the same ask (#1058)
            io.comment(n, policy_stop_comment(stop))
            io.queue_owner(n, stop)
            return False, tokens
    io.comment(n, f"Drain blocked after {RESTARTS} restarts of the builder on {worktree}. Last reason: {note}")
    return False, tokens


def drain(io, state: dict, sleep=time.sleep, say=print) -> int:
    """Run the loop until no story is left to start. Returns 0 when it ended, 1 when GitHub could not be read."""
    running: dict = {}
    pool = ThreadPoolExecutor(max_workers=max(1, io.limit()))
    waits, reported = 0, set()
    try:
        while True:
            issues = io.list_open()
            if issues is None:
                say("Drain stopped: the open stories were not read.")
                return 1
            skip = set(state["closed"]) | set(state["blocked"]) | {i["number"] for i in running.values()}
            todo = []
            for issue in sorted((i for i in issues if i["number"] not in skip and not is_epic(i)), key=rank):
                if why := skip_reason(issue):  # each skipped story is named once per drain, with the reason (#1014)
                    if issue["number"] not in reported:
                        reported.add(issue["number"])
                        say(f"Skipped #{issue['number']}: {why}.")
                    continue
                todo.append(issue)
            busy = [intake.files_area(i.get("body") or "") for i in running.values()]  # one overlap rule, shared with the planner (#1014)
            started = False
            for issue in todo:
                if len(running) >= io.capacity():
                    break
                areas = intake.files_area(issue.get("body") or "")
                if any(intake.overlaps(areas, b) for b in busy) or io.claimed(issue):
                    continue
                io.claim(issue["number"])
                running[pool.submit(work_story, io, issue, state)] = issue
                busy.append(areas)
                started = True
            io.beat([i["number"] for i in running.values()])
            if not running:
                if todo and not started and waits < FULL_WAITS and io.capacity() == 0:
                    waits += 1
                    sleep(300)
                    continue
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
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
                (state["closed"] if closed else state["blocked"]).append(issue["number"])
            io.beat([i["number"] for i in running.values()])
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


def status_page() -> str:
    """The page the run lock names for watching a run: the status digest until the status page lands (#990)."""
    try:
        from lib import cmd_status
        return str(cmd_status.digest_path())
    except Exception:  # noqa: BLE001 -- a missing page never stops a run
        return ""


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
        for n in taken.get("building") or []:
            io.release(n)
    return True


def command_drain(argv: list[str], io_factory=Io, sleep=time.sleep) -> int:
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
    if not take_run(io, slug, f"drain {repo.name}"):
        return 0
    state = new_state()
    try:
        with run_lock.Heartbeat(slug, pid):
            code = drain(io, state, sleep=sleep)
            while code == 0 and run_lock.release(slug, pid):  # a story another thread queued as this run ended is worked before the lock goes
                code = drain(io, state, sleep=sleep)
        return code
    finally:
        run_lock.release(slug, pid)
