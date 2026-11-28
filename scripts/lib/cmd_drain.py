"""Launcher command `drain`: `olivercode drain REPO` works a repo's open stories until none remain (#707).

It lists open stories through REST (epics, claimed and owner-gated stories are skipped), orders them P0 first, starts headless builders up to the builder cap
and never two whose stories name the same files, then drives each one run -> validate -> `olivercode land` -> comment and close on REST. A builder that exits
before its story lands restarts on the same worktree, up to RESTARTS times, then the blocker is commented on the story and drain moves on. `olivercode dispatch N`
builds one story through the same `work_story`. A drain whose own code moved under it starts itself again, and one whose validation calls a command
that is gone starts no new story (#1480). A story whose validation fails the way the base branch's does is held with no restart (#1481). A bundled story, and one
a reader held or its spend ceiling stopped, is split by one session instead of built (#1502). Every outside effect goes through the `Io` object, so
tests inject fakes and never touch the machine or GitHub.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from lib import agent_loop, cmd_dispatch, cmd_land, cmd_owner, failure_log, gh_budget, gitfiles, intake, local_config, model, policy, run_lock, validated
from lib.open_issues import fetch as fetch_open, owner_gated, rank
from lib.cmd_land import command_land
from lib.validate_gates import PROGRESS
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
PARKED = re.compile(r"shares [^\n]* in its Files area|Size \w+ is too large for one builder", re.I)
RETURNED = "Back to Ready:"
HELD = "Held by the fresh reader"  # how a held comment starts, and FINDING what its finding follows, so the next build can read it back (#1474)
FINDING = "\n\nFinding:\n"
CAPPED = "Drain stopped: Spend $"  # how a spend ceiling's comment and stopped row start (#1502)
PARK = "Parked: "  # how the comment on a story that was split, or could not be, starts (#1502)
SPLIT_FROM = r"^\W*Split from:\s*#"  # the line each story filed by a split carries, followed by its parent's number
SPLIT_DONE = "SPLIT DONE"  # the splitting session's last line when its stories cover the whole parent
SPLIT_TURNS = 60
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")  # the repo's own people, whose text may go into a model's brief
SPLIT_BRIEF = (
    "Split story #{n} of {slug} into S stories. The drain does not build it, because {why}.\n"
    "Read {skill} and file through it (\"File a story or epic\"), with the config {config}. Its scripts sit in the scripts folder beside it. "
    "Edit no file of the repo, start no agent and write each body to a file under {folder}.\n"
    "- File {least} or more stories of Size S, each holding one fix, with its own `Files area:` line of at most {most} files and no `## Findings` or `## Fixes` list\n"
    "- Keep this story's Epic line and Priority, put the line `Split from: #{n}` in each body, name #{n} and the sibling stories on its `Existing coverage checked:` line, and set each card to Ready\n"
    "- Cover everything this story asks. Copy each part of the reader's finding below into the story that must satisfy it\n"
    "- A story that must land after another, or after a story that blocks this one, gets GitHub's dependency link: `gh api -X POST repos/{slug}/issues/NUMBER/dependencies/blocked_by -F issue_id=BLOCKER_ID`. A story that #{n} blocks gets the same link to each new story\n"
    "- Leave #{n} open, since the runner closes it and names the new stories\n"
    "- Stories already filed from #{n}, which you never file again: {filed}\n"
    "End your reply with the line `" + SPLIT_DONE + "` only when every part of #{n} is covered. When you cannot split it, file nothing and say why.\n\n"
    "Story #{n}: {title}\n\n{body}\n\nThe reader's latest finding:\n{finding}\n")
GONE = "is not a valid command"  # what `olivercode` prints for a command it no longer has (#1480)
# Lines that differ between two runs of one failure or say nothing of it: validate_gates' timings, land's own closing lines and the smoke banner (#1481)
NOISE = (PROGRESS, "=== validate: never started", "validate: gates took", "=== validate: python smoke tests FAILED", "--- validate failed", "RESULT ")
SMOKE_SUMMARY = re.compile(r"Ran \d+ tests across \d+ modules, \d+ failed: (.+)")  # smoke_runner's line naming the failed modules


class NotTheStorys(RuntimeError):
    """A failed validation the story did not cause, so it counts no failure and starts no restart. The message is the failing line, `key` is where the
    run's state keeps the story and `cause` is what its comment says."""

    key = cause = ""


class CommandGone(NotTheStorys):
    """A failed validation called a command that no longer exists. The fault is in the code that ran it (#1480)."""

    key, cause = "gone", "validation calls a command that is gone"


class BaseFails(NotTheStorys):
    """The base branch fails validation with the story's own failing line, so the fault is in the branch or the machine (#1481)."""

    key, cause = "base", "the base branch fails validation with the same failing line"


def stop_if_gone(tail: str) -> None:
    """Raise CommandGone with the line of a failed validation's tail that says a command is gone (#1480)."""
    if line := next((line.strip() for line in tail.splitlines() if GONE in line), ""):
        raise CommandGone(line)


def failing_line(tail: str) -> str:
    """The line a story's failed validation and the base's are compared by (#1481): the last one that says FAIL or BLOCKED or names the failed smoke
    modules, since a gate that passed may print after the one that failed, else the last line. Timing lines are left out, and the smoke line loses its counts."""
    lines = []
    for line in (raw.strip() for raw in tail.splitlines()):
        if not line or line.startswith(NOISE):
            continue
        if smoke := SMOKE_SUMMARY.match(line):  # a story that adds tests changes the counts and how a module is split
            line = "smoke tests FAILED: " + ", ".join(sorted({name.split("#")[0] for name in smoke[1].split(", ")}))
        lines.append(line)
    return ([line for line in lines if "FAIL" in line or "BLOCKED" in line] or lines or ["validation failed"])[-1]


def skip_reason(issue: dict, repo: Path | None = None) -> str:
    """Why drain does not start an open story now, or '' when it may. Only a Ready story with a board Size and a Files area is built (#1014)."""
    if owner_gated(issue):
        return "it is owner-gated"
    if issue.get("status") != "Ready":
        return f"its board Status is {issue.get('status') or 'empty'}, not Ready"
    if not issue.get("size"):
        return "it has no Size on the board"
    if (size := intake.size_of(issue)) in ("L", "XL") and not intake.bundled(issue.get("body") or ""):  # the text's Size routes the builder, so it also decides the refusal (#1342); a bundled one goes on to be split (#1502)
        return f"its Size is {size}, so it needs splitting into S and M stories"
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
    return {"closed": [], "blocked": [], "sessions": 0, "tokens": 0, "restarts": {}, "skipped": {}}


def skipped_summary(skipped: dict) -> str:
    """The run-end sentence naming how many stories the run did not start for each reason, or '' when it started every one it met (#1456). `skipped` maps a story number to its reason."""
    labels = {"blocker": "blocked by an open story", "owner": "owner-gated", "size": "too large to build and not split"}
    counts = [f"{n} {labels[k]}" for k in labels if (n := sum(1 for v in skipped.values() if v == k))]
    return f" Not started: {', '.join(counts)}." if counts else ""


class Io:
    """Every outside effect of a drain. Tests replace the methods; the defaults use REST, git, the headless loop and `olivercode land`."""

    def __init__(self, repo: Path, slug: str, agent: str = "drain", runner=None, parallel: int | None = None):
        self.repo, self.slug, self.agent, self.runner, self.parallel = repo, slug, agent, runner, parallel
        self.resumed: dict[int, str] = {}  # story number -> the resume note for a branch an earlier session left (#877)
        self.fetched: set[int] = set()  # stories whose origin fetch this run already made, so a story costs one fetch
        self.claim_start: dict[int, float] = {}  # story number -> when this run claimed it, never refreshed (#1306)
        self.claimed_at: dict[int, float] = {}  # story number -> when its claim comment was last posted, so a long build refreshes it
        self.said: dict[int, str] = {}  # story number -> its last comment, which is the reason a stopped row records (#1291)
        self.saved: set[int] = set()  # stories whose open card goes to Backlog: a stopped builder's work was committed to story/N (#1328), or a split began (#1502)
        self.built_at: dict[int, str] = {}  # story number -> the stamp its current builder started, which bounds the policy asks it can hit (#1058)

    def gh(self, args: list[str]):
        """`gh` through the runner a caller injected, else the shared one that honors the GitHub hold."""
        return (self.runner or cmd_dispatch.gh)(args)

    def branch(self) -> str:
        """The repo's default branch, which every ancestry and count check reads (#877)."""
        return agent_loop.default_branch(self.repo)

    def code_head(self) -> str:
        """The commit OliverCode's own checkout is on, which is the code a drain started now would run, or "" when git cannot say (#1480)."""
        ran = subprocess.run(["git", "-C", str(OC_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
        return ran.stdout.strip() if ran.returncode == 0 else ""

    def validation(self) -> list[str] | None:
        """The repo's own validation command, which a story needs before a builder starts (#1012)."""
        return agent_loop.validation_command(self.repo)

    def base_failure(self, fresh: bool = False) -> str:
        """The failing line of the validation's output when it fails on a worktree of origin's default branch, else "" (#1431). A tree with a recorded pass is not validated again unless `fresh`, since an old pass says nothing about the machine now (#1481), and a timeout is rerun once and then read as unknown (#1436).
        shortcut: a base that cannot be fetched or checked out counts as passing, upgrade when a drain needs to stop on an unreadable base."""
        git = ["git", "-C", str(self.repo)]
        if subprocess.run([*git, "fetch", "-q", "origin", self.branch()], capture_output=True, text=True).returncode:
            return ""
        folder = placement_config().worktrees  # under repoRoot/_worktrees, where the temp folder's size slowed the check 12-fold (#1433)
        folder.mkdir(parents=True, exist_ok=True)
        wt = Path(tempfile.mkdtemp(prefix=f"{self.repo.name}-base-", dir=folder))
        try:
            if subprocess.run([*git, "worktree", "add", "--detach", "-f", str(wt), f"origin/{self.branch()}"], capture_output=True, text=True).returncode:
                return ""
            cmd_land.prepare_worktree(wt, self.repo)
            if agent_loop.validation_command(wt) is None:
                return ""
            if not fresh and validated.is_validated(validated.working_tree(wt)):  # land recorded a full pass for this tree, so nothing is learned by running it again (#1436)
                return ""
            code, tail = agent_loop.validate_code(wt)
            if code == agent_loop.TIMED_OUT:  # a slow machine is not a red staging: rerun once, then build everything
                code, tail = agent_loop.validate_code(wt)
                if code == agent_loop.TIMED_OUT:
                    print("Base validation timed out twice, so staging is unknown and stories of every priority build (#1436).")
                    return ""
            return "" if code == 0 else failing_line(tail)
        finally:
            subprocess.run([*git, "worktree", "remove", "--force", str(wt)], capture_output=True, text=True)
            shutil.rmtree(wt, ignore_errors=True)

    def ci_failure(self) -> str:
        """The newest completed CI run on origin's default branch, named by its address, when it and the one before it failed, else "" (#1482). One flaky run is not a red staging (#1492).
        shortcut: a run that cannot be read counts as passing, upgrade when a story is seen to land on red CI after a failed read."""
        run = intake.failed_ci_run(self.slug, lambda args: self.gh(["api", *args]), self.branch(), runs=2)
        return f"CI run {run.get('html_url', '')} failed" if run else ""

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
        """The board's card for each story number, from the shared board copy. None when the board cannot be read, so drain stops
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
        """Builders this run may hold now: --parallel N, else the machine limit less what other repos' runs are building. At most 1 while the
        1-minute load average is above twice the core count, so a heavy load slows new starts and never ends the run (#1487).
        shortcut: a fix round after a failed landing starts without asking, as it does past maxBuilders, upgrade when a loaded run is seen holding two builders."""
        free = self.parallel or max(0, local_config.max_builders() - run_lock.building_elsewhere(self.slug))
        return min(free, 1) if os.getloadavg()[0] > 2 * (os.cpu_count() or 1) else free

    def beat(self, building: list[int]) -> None:
        """Tell the repo's run lock which stories are building now (#992)."""
        run_lock.beat(self.slug, os.getpid(), time.time(), building)

    def fetch(self, n: int) -> None:
        """Fetch origin's default branch once for story n."""
        if n not in self.fetched:
            self.fetched.add(n)
            subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin", self.branch()], capture_output=True, text=True)

    def worktree(self, n: int) -> Path:
        """Create story/N's worktree from origin's default branch, or reuse the one a restart finds."""
        path = placement_config().worktrees / f"{self.repo.name}-{n}"
        self.fetch(n)  # a base older than origin repeats landed work (#1011)
        problems, self.resumed[n] = cmd_land.resume_worktree(self.repo, path, str(n), f"origin/{self.branch()}")
        if problems:
            raise RuntimeError("; ".join(problems))
        if self.resumed[n] and (finding := self.held_finding(n)):
            self.resumed[n] += cmd_land.HELD_NOTE.format(finding=finding)
        return path

    def own_comments(self, n: int) -> list[str]:
        """Story n's comments by the repo's own people, oldest first, since their text may go into a model's brief (#1474).
        shortcut: a failed read counts as no comment, upgrade when a resumed build or a split is seen to miss one."""
        raw = self.gh(["api", f"repos/{self.slug}/issues/{n}/comments", "--paginate", "--jq", ".[] | {body, author_association} | @json"])
        rows = (json.loads(line) for line in (raw.stdout.splitlines() if raw.returncode == 0 else []) if line.strip())
        return [row.get("body") or "" for row in rows if isinstance(row, dict) and row.get("author_association") in TRUSTED]

    def held_finding(self, n: int) -> str:
        """The finding in story n's latest held comment, or '' when it has none (#1474)."""
        return next((body.partition(FINDING)[2] for body in reversed(self.own_comments(n)) if body.startswith(HELD)), "")

    def run_rows(self, n: int) -> list[dict]:
        """The run log's rows for story n and its reader, oldest first.
        shortcut: a reader's row names no repo, so another repo's story of the same number counts too; upgrade when a split is seen to carry a foreign finding."""
        from lib import cmd_status  # local import: cmd_status loads modules that import this one
        return [r for r in cmd_status.run_log() if r.get("story") in (f"story-{n}", f"story-{n}-review") and r.get("repo", self.repo.name) == self.repo.name]

    def split_cause(self, issue: dict) -> str:
        """Why story N must be split and not built, or '' when it may build (#1502): it is bundled, or an earlier build was held by the reader or
        reached its spend ceiling, which the run log and the story's comments both record. A Backlog story is split only when this machine's run log
        shows it stopped and no split was tried, so one that waits for another reason is left alone."""
        n = issue["number"]
        rows = self.run_rows(n)
        stops = [str(r.get("reason") or "") for r in rows if r.get("stage") == "stopped"]
        backlog = issue.get("status") == "Backlog"
        if backlog and (not stops or any(r.get("stage") == "parked" for r in rows)):
            return ""
        said = self.own_comments(n) if issue.get("comments") else []
        if backlog and any(body.startswith(PARK) for body in said):
            return ""
        if why := intake.bundled(issue.get("body") or ""):
            return why
        for text in reversed([*said, *stops]):
            if text.startswith(HELD):
                return "the fresh reader held an earlier build"
            if text.startswith(CAPPED):
                return "an earlier build reached its spend ceiling"
        return ""

    def split_children(self, n: int) -> list[dict] | None:
        """The open stories the repo's own people filed from story n, or None when the open issues cannot be read (#1502)."""
        opened = fetch_open(self.slug)
        if opened is None:
            return None
        return sorted((i for i in opened if i.get("author_association") in TRUSTED and re.search(rf"{SPLIT_FROM}{n}\b", i.get("body") or "", re.M)),
                      key=lambda i: i["number"])

    def split(self, issue: dict, why: str) -> dict:
        """One splitting session on story N, which files S stories through the backlog skill (#1502). The runner reads them back from GitHub, then
        closes the parent as not planned with a comment naming them. A split that fails leaves the parent open in Backlog with the reason. Returns
        {'into': the numbers filed, 'problem': why the parent stays open or '', 'tokens': int}, or {'limited': reason, 'tokens': int} at the usage
        limit, where the story is split by a later run. Either way a `parked` run-log row is what `status` and `watch` show."""
        n, body = issue["number"], issue.get("body") or ""
        story = f"story-{n}"
        self.set_card(n, {"status": "Backlog"})
        self.saved.add(n)  # an open parent keeps that card, at the usage limit too
        agent_loop.log_stage(story, self.repo.name, "splitting", reason=why)
        before = self.split_children(n)
        least = 1 if not re.search(SPLIT_FROM, body, re.M) else 2  # one rewrite per lineage, so a story from a split that stops again must get smaller
        problem, reply = "the open stories could not be read" if before is None else "", {}
        if not problem:
            found = next((str(r.get("findings")) for r in reversed(self.run_rows(n)) if r.get("review") == "findings"), "")
            config = self.config_path()
            with tempfile.TemporaryDirectory(prefix=f"split-{n}-") as folder:
                prompt = SPLIT_BRIEF.format(n=n, slug=self.slug, why=why, skill=OC_ROOT / "skills" / "backlog" / "SKILL.md", config=config, folder=folder,
                                            least=least, most=intake.BUNDLE_FILES, filed=", ".join(f"#{i['number']}" for i in before) or "none",
                                            title=issue.get("title", ""), body=body, finding=found or self.held_finding(n) or "none")  # the run log first: a held comment may name only a reader that failed
                try:
                    reply = model.run_cli(prompt, str(self.repo), allowed_tools="Read,Grep,Glob,Bash,Write", max_turns=SPLIT_TURNS,
                                          session=f"{story}-split", model=agent_loop.LADDER[1])
                except (model.ModelError, OSError, subprocess.SubprocessError) as exc:
                    problem = str(exc)
        tokens, text = reply.get("tokens", 0), (reply.get("text") or "").strip()
        if reply:
            agent_loop.log_round(f"{story}-split", 1, agent_loop.LADDER[1], reply)
            if reply["code"] != 0:
                if agent_loop.USAGE_LIMIT.search(f"{text}\n{reply.get('stderr') or ''}"):
                    return {"limited": f"{agent_loop.USAGE_LIMIT_REASON}: {agent_loop.exit_reason(reply, 1, unit='attempt')}", "tokens": tokens}
                problem = agent_loop.exit_reason(reply, 1, unit="attempt")
        children = self.split_children(n) or []
        numbers = [i["number"] for i in children]
        if not problem:
            wrong = [f"#{i['number']}" for i in children if intake.size_of(i) not in intake.SMALL
                     or not intake.files_area(i.get("body") or "") or intake.bundled(i.get("body") or "")]
            if not text.endswith(SPLIT_DONE):
                problem = f"the splitting session did not finish: {text[-300:]}"
            elif len(children) < least:
                problem = f"it filed {len(children)} stories and needs at least {least}"
            elif wrong:
                problem = f"{', '.join(wrong)} is not an S story with one fix and a Files area"
        named = ", ".join(f"#{i}" for i in numbers)
        if not problem:
            self.comment(n, f"{PARK}{why}. Split into {named}, so this story is closed and is not built.")
            if self.gh(["api", "-X", "PATCH", f"repos/{self.slug}/issues/{n}", "-f", "state=closed", "-f", "state_reason=not_planned"]).returncode != 0:
                problem = "GitHub did not close it"
            else:
                lanes = backlog_config(self.repo).get("fields", {}).get("status", {}).get("options", {})
                self.set_card(n, {"status": "Done" if "Done" in lanes else "Complete"})
        if problem:
            self.comment(n, f"{PARK}{why}. Not split: {problem}. It stays in Backlog and is not built." + (f" Filed from it: {named}." if named else ""))
        agent_loop.log_stage(story, self.repo.name, "parked", reason=f"{why}; not split: {problem}" if problem else why, into=numbers, split=not problem, title=issue.get("title", ""))
        return {"into": numbers, "problem": problem, "tokens": tokens}

    def config_path(self) -> Path:
        """The repo's backlog config, the local one when it has one."""
        return self.repo / (LOCAL_BACKLOG_CONFIG if (self.repo / LOCAL_BACKLOG_CONFIG).is_file() else BACKLOG_CONFIG)

    def build(self, issue: dict, worktree: Path, note: str) -> dict:
        """One headless builder session on the story: the brief holds the code the story names, and the
        model is the one the brief names (#1015), with a small story getting a third round (#890)."""
        n, size = issue["number"], intake.size_of(issue)
        extras = "".join(part + "\n" for part in (cmd_dispatch.file_excerpts(issue.get("body") or "", worktree)) if part)
        brief = cmd_dispatch.headless_brief(n, issue, self.agent, worktree, extras, note="\n".join(filter(None, (note, self.resumed.get(n, "")))))  # a restart keeps the resume note and its finding (#1474)
        builder, _reader, why = intake.models(issue, f"story-{n}")
        files = intake.files_area(issue.get("body") or "")
        review = agent_loop.review_mode(size, issue.get("labels") or (), files, intake.priority_of(issue))
        self.built_at[n] = failure_log.stamp()
        agent_loop.log_stage(f"story-{n}", self.repo.name, "building")

        def check(cwd):  # raising here ends the loop before the failed round counts toward a fix round or a larger model (#1480)
            passed, tail = agent_loop.validate(cwd)
            if not passed:
                self.blame(tail)
            return passed, tail

        return agent_loop.run_loop(brief, worktree, f"story-{n}", model_name=builder, why=why, check=check,
                                   rounds=agent_loop.MAX_ROUNDS + (1 if size in intake.SMALL else 0), review_mode=review, repo=self.repo.name)

    def blame(self, tail: str) -> None:
        """Raise when a failed validation is not the story's own: it calls a command that is gone (#1480), or the base, validated now, fails with the same failing line (#1481)."""
        stop_if_gone(tail)
        line = failing_line(tail)
        if self.base_failure(fresh=True) == line:
            raise BaseFails(line)

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
        removed its worktree still counts. It shares the story's one fetch, since a land's push moves origin's ref in this repo."""
        branch = self.branch()
        self.fetch(n)
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
        elif refused := re.search(r"RESULT (\S+)", out.stdout):  # a refused landing shows as stopped at once, not as still landing (#1486)
            agent_loop.log_stage(f"story-{n}", self.repo.name, "stopped", reason=f"Landing refused: {refused.group(1)}")
            if refused.group(1) == "validate-failed" and (log := re.search(r"\(log: (.+?)\)", out.stdout)):
                try:  # land prints only the result, so the validation's tail is read from its log
                    text = Path(log.group(1)).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if text:
                    self.blame(agent_loop.gate_tail(text))
        return out.returncode == 0, (out.stdout + out.stderr).strip()[-300:]

    def stack(self, items: list[tuple[Path, int]]) -> bool:
        """Validate several committed stories once as a stack, so each one's land reuses the pass (#1317)."""
        return cmd_land.stack([(wt, str(n)) for wt, n in items])

    def comment(self, n: int, body: str) -> None:
        self.said[n] = body
        self.gh(["api", "-X", "POST", f"repos/{self.slug}/issues/{n}/comments", "-f", f"body={body}"])

    def close_by_script(self, worktree: Path, n: int, why: str, stage: str = "landed") -> tuple[bool, str]:
        """Log the builder entry for the commit that names the story on origin's default branch, then close the story through complete_story.py
        with the landing's output as its Run output (#912). `stage` is the run log row for the close: "landed" for a build, "closed" for a story already waiting in QA (#1377). Returns (closed, the refusal when the close was not made)."""
        branch = self.branch()
        log = subprocess.run(["git", "-C", str(self.repo), "log", f"origin/{branch}", "-n", "400", *self.since_claim(n), "--format=%H%x09%s"], capture_output=True, text=True)
        sha = next((line.split("\t")[0] for line in log.stdout.splitlines() if f"(#{n})" in line), "")
        if not sha:
            return False, f"no commit for (#{n}) is on origin/{branch}"
        files = subprocess.run(["git", "-C", str(self.repo), "diff-tree", "--no-commit-id", "--name-only", "-r", sha], capture_output=True, text=True).stdout.split()
        config = self.config_path()
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
            agent_loop.log_stage(f"story-{n}", self.repo.name, stage, reason=why if stage == "closed" else "")
            return True, ""
        return False, (done.stdout + done.stderr).strip()[-500:]

    def staged(self) -> bool:
        """True when this repo is OliverCode's own and lands on the owner's engineBranch, where a story closes on staging and main is a label (#1330)."""
        return bool(agent_loop.setting("engineBranch")) and agent_loop.is_engine_repo(self.repo)

    def find_bugs(self) -> None:
        """Read the stops this run wrote, and red CI, for bugs, filed in this repo, or in OliverCode's origin for a fault in its own code (#1371, #1397)."""
        intake.bugs(self.repo)

    def stopped(self, n: int, reason: str) -> None:
        """Append the stopped row that says why a story left the status line (#1291)."""
        agent_loop.log_stage(f"story-{n}", self.repo.name, "stopped", reason=reason)

    def set_card(self, n: int, fields: dict) -> None:
        """Queue a board write of `fields` on story n's card (#1348)."""
        cfg = backlog_config(self.repo)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": fields}]}]))

    def parked_for(self, n: int) -> str:
        """The cause a Backlog story was parked for ('overlap' or 'size'), or '' when its latest comment about it is not a parking or none is (#1348)."""
        raw = self.gh(["api", f"repos/{self.slug}/issues/{n}/comments", "--paginate", "--jq", ".[].body | @json"])
        cause = ""
        for body in (json.loads(line) for line in (raw.stdout.splitlines() if raw.returncode == 0 else []) if line.strip()):
            if RETURNED in body or body.startswith(PARK):  # a split or a failed one is never undone by an older parking comment (#1502)
                cause = ""
            elif m := PARKED.search(body):
                cause = "overlap" if "Files area" in m.group(0) else "size"
        return cause

    def keep_open(self, n: int, reason: str = "") -> None:
        """After a builder that did not land: say why on the story, reopen it when something closed it, and put its card back to Ready (#877)."""
        self.stopped(n, reason or self.said.get(n, ""))
        if reason:
            self.comment(n, f"Builder stopped without landing: {reason}")
        done = self.gh(["api", f"repos/{self.slug}/issues/{n}", "--jq", ".state"])
        if done.returncode == 0 and done.stdout.strip() == "closed":
            self.gh(["api", "-X", "PATCH", f"repos/{self.slug}/issues/{n}", "-f", "state=open"])
        cfg = backlog_config(self.repo)
        status = "Backlog" if n in self.saved else "Ready"  # saved work waits for a split, not a rebuild (#1328)
        cmd_dispatch.batch_project.with_queue(lambda q: (None, q + [{"cfg": cfg, "issues": [{"number": n, "fields": {"status": status}}]}]))

    def save_work(self, worktree: Path, n: int) -> list[str]:
        """Commit and push what a stopped builder left uncommitted in its worktree to story/N, and return the files changed. A clean worktree
        makes no commit and returns []. The push is the branch only, so nothing lands until a story built from it passes validation and review (#1328).
        shortcut: --no-verify, since partial work cannot pass the commit hooks, and the landing runs validation and review before anything reaches main."""
        status = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"], capture_output=True, text=True)
        files = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
        if not files:
            return []
        steps = (["add", "-A"], ["commit", "-q", "--no-verify", "-m", f"Partial work from a stopped builder (#{n})"], ["push", "--no-verify", "origin", f"HEAD:refs/heads/story/{n}"])
        for step in steps:
            done = subprocess.run(["git", "-C", str(worktree), *step], capture_output=True, text=True)
            if done.returncode != 0:
                return []
        self.saved.add(n)
        return files

    def refresh_claims(self, now: float | None = None) -> None:
        """While this run is alive, renew each claim it holds: the local claim every call, and the claim comment once a quarter of the
        claim window has passed. A run that dies stops renewing, so its claim expires (#1033)."""
        now = now or time.time()
        for n, posted in list(self.claimed_at.items()):
            cmd_dispatch._local_claim(self.slug, n, now, write=self.agent)
            if now - posted < cmd_dispatch.log_action.CLAIM_HOURS * 900 or gh_budget.refusal() or gh_budget.reserve_write(lane="drain"):
                continue
            body = cmd_dispatch.log_action.build_claim(self.agent, cmd_dispatch.datetime.datetime.fromtimestamp(now, cmd_dispatch.datetime.timezone.utc))
            cmd_dispatch.log_action.post_comment(self.slug, n, body, lambda args: self.gh(["api", *args]))
            self.claimed_at[n] = now

    def release(self, n: int) -> None:
        """Drop the local claim and post the release comment, so no outcome leaves the story held (#877)."""
        self.claimed_at.pop(n, None)
        cmd_dispatch._local_claim(self.slug, n, time.time(), clear=True)
        if gh_budget.refusal() or gh_budget.reserve_write(lane="drain"):
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
        agent_loop.STORY_SLUG[f"story-{n}"] = self.slug
        agent_loop.SPEND[f"story-{n}"] = agent_loop.logged_spend(f"story-{n}", self.slug)  # the ceiling covers what earlier drains spent (#1481)
        agent_loop.log_stage(f"story-{n}", self.repo.name, "claimed")
        if gh_budget.refusal() or gh_budget.reserve_write(lane="drain"):
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
    finish(io, worktree, n, why)
    return True, why


def finish(io, worktree: Path, n: int, why: str, stage: str = "landed") -> None:
    """Close a landed story through complete_story.py, which accepts a commit on the engine branch as well as the default branch (#1330).
    A refused close comments the gate's message, logs its one stopped row and raises CloseRefused (#912, #1291)."""
    closed, reason = io.close_by_script(worktree, n, why, stage=stage)
    if not closed:
        io.comment(n, f"Close refused by complete_story.py: {reason}")
        io.stopped(n, f"Close refused: {reason}")  # the refusal is the reason status shows, and bug intake reads its prefix (#1291, #1371)
        notify(f"#{n} landed but didn't close. Nothing needed from you.")  # the gate's message stays in the comment and the stopped row
        raise CloseRefused(reason)


def close_waiting_in_qa(io, say=print) -> bool:
    """On an engine repo, close each open story whose card waits in QA and whose commit is on the engine branch, through the same close
    a fresh landing gets. A QA story with no commit there stays open and is named (#1330). Returns False when the board read returned
    nothing, so the drain tries again on its next read (#1345)."""
    if not io.staged():
        return True
    issues = io.list_open()
    if issues is None:
        say("Put off closing the stories waiting in QA: the open stories were not read.")
        return False
    for issue in issues:
        n = issue["number"]
        if issue.get("status") != "QA":
            continue
        if not io.landed(io.repo, n):
            say(f"Left open #{n}: its card is in QA and no commit for it is on the engine branch.")
            continue
        try:
            finish(io, io.repo, n, "already on the engine branch", stage="closed")
        except CloseRefused as exc:  # finish has commented and logged the refusal
            say(f"Left open #{n}: {exc}")
    return True


def work_story(io, issue: dict, state: dict, queue=None, resume: tuple[int, str] | None = None) -> tuple[bool | None, int]:
    """Drive one story to landed, restarting its builder on the same worktree. Returns (closed, tokens used here). A story that did not land is left open on Ready, and the claim is released on every exit. Each builder takes one story, so no commit carries two stories' work (#988).
    With `queue`, the builder's slot ends at its commit: the story is handed to the landing queue, closed comes back None and the claim stays until the queue settles it. `resume` is (attempt, note) for a fix round after a failed landing (#1317)."""
    n, handed = issue["number"], False
    try:
        closed, used = _work_story(io, issue, state, queue, resume)
        handed = closed is None
        if closed is False and n not in state.get("split", {}):  # a split story is closed and stays closed (#1502)
            io.keep_open(n)  # a story that did not land stays open with its card in Ready (#877)
            if n in state.get("parked", {}):
                notify(f"#{n} is parked. `olivercode status` says why.")
            elif n not in state.get("limited", []):  # the usage limit already sent its own notification
                notify(f"#{n} didn't land yet. It'll try again on its own.")  # the reason stays in the story comment and the run log (#1325, #1374)
        return closed, used
    except NotTheStorys as exc:
        put_back(io, state, n, exc)
        return False, 0
    except CloseRefused:  # a refused close leaves the story with the gate's message and its one stopped row (#1011)
        return False, 0
    finally:
        if not handed:
            io.release(n)


def put_back(io, state: dict, n: int, exc: NotTheStorys) -> None:
    """Record a story whose failed validation it did not cause, comment the reason and the line and put the story back on Ready. No builder restarts for it, and this run does not take it again (#1480, #1481)."""
    state.setdefault(exc.key, {})[n] = str(exc)
    if isinstance(exc, BaseFails):  # for a gone command the drain sends the one notification (#1480)
        notify(f"#{n} didn't land yet. It'll try again on its own.")
    io.comment(n, f"Drain stopped: {exc.cause}, so this story counts no failure. Line: {exc}")
    io.keep_open(n)


def split_story(io, state: dict, issue: dict, why: str, tokens: int = 0) -> tuple[bool, int]:
    """Split a story that is never built again, in place of its next build (#1502). Its stopped row comes first, so a later run reads why even when the
    split never finishes. At the usage limit the story is left for a later run, like a build. Returns work_story's (closed, tokens)."""
    n = issue["number"]
    io.stopped(n, getattr(io, "said", {}).get(n) or why)
    out = io.split(issue, why)
    if out.get("limited"):
        state.setdefault("limited", []).append(n)
        io.comment(n, f"Drain stopped: {out['limited']}")
        notify("Paused at the Claude usage limit. Picks up when it resets.")
    elif out["problem"]:
        state.setdefault("parked", {})[n] = why
    else:
        state.setdefault("split", {})[n] = out["into"]
    return False, tokens + out.get("tokens", 0)


def held_comment(worktree: Path, finding: str) -> str:
    """The one comment a held story gets: that nothing was pushed, where the branch is kept, and the finding itself (#975)."""
    return f"{HELD}, so nothing was pushed. The branch is kept in {worktree} and the story goes to Backlog to be split.{FINDING}{finding[:2000]}"


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
    rule, _, command = asks[-1][len("ask "):].partition(" | ")  # the hooks log the rule, then the command that hit it (#1473)
    return {"rule": rule, "command": command, "gate": gate, "finding": finding, "file": named.group(0) if named else ""}


def policy_stop_comment(stop: dict) -> str:
    """The one comment a policy-stopped story gets: the rule and gate, the last finding, the file it named and the one next action (#1058)."""
    return (f"Stopped by the policy, so drain starts no restart: {stop['rule']} answered this builder's commit with ask, and a headless session cannot answer it.\n"
            f"- Gate: {stop['gate'] or 'none'}\n"
            f"- Last finding: {stop['finding'] or 'none'}\n"
            f"- File: {stop['file'] or 'none named'}\n"
            f"- Command: {stop.get('command') or 'none logged'}\n"
            "- Next: run the diagnosing-bugs loop on the gate's finding, then return this story to Ready.")


def stops_here(io, n: int, worktree: Path, note: str, landing: bool) -> bool:
    """True when a failed round must not restart the builder, after commenting why: a refused push is not the builder's to fix (#1296), and a policy ask
    answers a headless builder with no one to answer it, so a restart would hit the same ask (#1058). A builder that got past its ask and committed is
    not stopped by it: its commit lands, or its landing failure is the reason (#1473)."""
    if landing and "push-failed" in note:
        io.comment(n, f"Drain blocked: {note}")
        return True
    if io.commits(worktree) > 0:
        return False
    stop = io.policy_stop(n, worktree)
    if stop:
        io.comment(n, policy_stop_comment(stop))
        io.queue_owner(n, stop)
        return True
    return False


def _work_story(io, issue: dict, state: dict, queue=None, resume: tuple[int, str] | None = None) -> tuple[bool | None, int]:
    n, tokens = issue["number"], 0
    first, note = resume or (0, "")
    lead = None if resume else io.landed_lead(issue)
    if lead:  # the work landed under another story, so a fresh build would repeat it on main; the owner decides (#988)
        io.comment(n, f"Not built: commit {lead[0][:12]} ({lead[1]}) on the default branch changed this story's files, so its work most likely landed under that story. The owner decides whether this story closes.")
        return False, 0
    if not resume and not io.pending(n) and io.landed(io.repo, n):  # its commit is on the default branch and no unlanded work waits in its worktree, so it closes through the script and no builder starts (#1011)
        finish(io, io.repo, n, "already on the default branch")
        return True, 0
    if not resume and (why := io.split_cause(issue)):  # no builder takes a bundled story, or one a hold or a ceiling stopped (#1502)
        return split_story(io, state, issue, why)
    if not resume and io.validation() is None:  # no builder starts in a repo that nothing can validate (#1012)
        io.comment(n, f"Drain blocked: {agent_loop.NO_VALIDATION}")
        return False, 0
    try:
        worktree = io.worktree(n)
    except RuntimeError as exc:
        io.comment(n, f"Drain blocked: the worktree was not created: {exc}")
        return False, 0
    if resume and stops_here(io, n, worktree, note, True):  # the failed landing was the last round's
        return False, 0
    for attempt in range(first, RESTARTS + 1):
        state["sessions"] += 1
        state["restarts"][n] = attempt
        out = io.build(issue, worktree, note)
        tokens += out.get("tokens", 0)
        if out.get("held"):  # a reader's finding that a fix did not clear holds the story, so the builder is not restarted (#975) and the story is split (#1502)
            io.comment(n, held_comment(worktree, out["held"]))
            return split_story(io, state, issue, "the fresh reader held its build", tokens)
        if out.get("reader_failed"):  # no finding, so the comment never starts with HELD, and no builder restarts (#1489)
            io.comment(n, f"Drain stopped: reader failed, so nothing was pushed. The branch is kept in {worktree} and the story goes back to Ready. {out['reader_failed']}")
            return False, tokens
        if out.get("usage_limit"):  # the story goes back to Ready unblocked, and the drain starts no new builder (#1299)
            state.setdefault("limited", []).append(n)
            io.comment(n, f"Drain stopped: {out['reason']}")
            notify("Paused at the Claude usage limit. Picks up when it resets.")
            return False, tokens
        if out.get("capped"):  # the story spent its size's ceiling, so no restart; the stopped row takes this comment as its reason (#1318), and the story is split (#1502)
            io.comment(n, f"Drain stopped: {out['reason']}")
            return split_story(io, state, issue, "its build reached the spend ceiling", tokens)
        if out.get("fatal"):  # a reason a restart cannot fix blocks the story and starts no new session (#1012)
            io.comment(n, f"Drain blocked: {out['reason']}")
            return False, tokens
        if out["done"]:
            if queue is not None and io.commits(worktree) > 0:  # the slot ends at the commit, and the landing queue validates and lands it (#1317)
                queue(issue, worktree, attempt)
                return None, tokens
            try:
                closed, note = land_and_close(io, worktree, n)
            except CloseRefused:  # work_story ends the story and logs no second row (#1297), so the tokens are counted here
                state["tokens"] += tokens
                raise
            if closed:
                return True, tokens
        else:
            note = out["reason"]
        if stops_here(io, n, worktree, note, bool(out["done"])):
            return False, tokens
    saved = io.save_work(worktree, n)
    if saved:  # the one comment names where the work is, so a split starts from it (#1328)
        io.comment(n, f"Builder stopped without landing, and its work is kept on branch story/{n}, which no drain lands by itself.\n- Files changed: {', '.join(saved)}\n- Stop reason: {note}")
    else:
        io.comment(n, f"Drain blocked after {RESTARTS} restarts of the builder on {worktree}. Last reason: {note}")
    return False, tokens


def land_batch(io, batch: list[tuple[dict, Path, int]], say=print) -> list[tuple[dict, Path, int, str, str]]:
    """Validate and land the committed stories of one batch, one batch at a time (#1317). Two or more first stack and pass one quick validation, which
    each story's own land reuses. A batch that fails that validation lands each story on its own, so each is validated alone and only the failing one fails.
    One story lands as it always did. Returns (issue, worktree, attempt, "closed" | "failed" | "refused" | "blameless", note) per story, where a
    blameless story's note is the NotTheStorys that says why."""
    if len(batch) > 1:
        io.stack([(wt, issue["number"]) for issue, wt, _ in batch])
    rows = []
    for issue, wt, attempt in batch:
        n = issue["number"]
        try:
            closed, note = land_and_close(io, wt, n)
            rows.append((issue, wt, attempt, "closed" if closed else "failed", note))
        except CloseRefused:  # the refusal is already on the story with its one stopped row
            rows.append((issue, wt, attempt, "refused", ""))
        except NotTheStorys as exc:
            rows.append((issue, wt, attempt, "blameless", exc))
    return rows


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
    the claims of the stories it was building and returns to Ready without waiting for their builders (#1076). No new story starts once OliverCode's
    checkout leaves the head the run started on, which `state['moved']` then names, or once a validation called a command that is gone (#1480)."""
    running: dict = {}
    pool = ThreadPoolExecutor(max_workers=max(1, io.limit()))
    lander = ThreadPoolExecutor(max_workers=1)  # one batch validates and lands at a time, so validation load stays bounded (#1317)
    waiting: deque = deque()  # committed stories the queue has not taken yet
    committed: dict = {}  # number -> issue of each story committed and not yet landed or sent back to a builder
    landing: dict = {}  # the one batch in flight: its future -> its stories
    waits, reported, filled, mismatched, unparked = 0, set(), set(), set(), set()
    stuck: dict = {}  # Backlog story number -> why it is split, read once per drain (#1502)
    skipped = state.setdefault("skipped", {})  # story number -> why the run did not start it (#1456)
    stopped = False
    hold_waited = False
    checked, base_red, told = (None, 0), "", ""  # closed and base-held counts at the last base check, its failing line, the red lines last said
    state.setdefault("head", io.code_head())  # the code this run started on (#1480)

    def halted() -> bool:
        """True once no new story may start. The first call that finds a gone command tells the owner (#1480)."""
        head = io.code_head()
        if head and state["head"] and head != state["head"]:
            state["moved"] = head
        if state.get("gone") and not state.get("gone_told"):  # kept in the state, so a second pass for a queued story says nothing again
            state["gone_told"] = True
            say(f"No new story starts: validation calls a command that is gone: {next(iter(state['gone'].values()))}")
            notify("Validation calls a command that no longer exists, so no new story starts.")
        return bool(state.get("moved") or state.get("gone"))

    def enqueue(issue: dict, worktree: Path, attempt: int) -> None:
        committed[issue["number"]] = issue
        waiting.append((issue, worktree, attempt))

    def settle(fut) -> None:
        batch = landing.pop(fut)
        try:
            rows = fut.result()
        except Exception as exc:  # a crashed queue blocks the stories it held and the run goes on
            say(f"The landing queue crashed: {exc!r}")
            rows = [(issue, wt, attempt, "crashed", repr(exc)) for issue, wt, attempt in batch]
        for issue, wt, attempt, status, note in rows:
            n = issue["number"]
            committed.pop(n, None)
            if status == "failed":  # only the failing story goes back to a builder, as a fix round on the same worktree
                running[pool.submit(work_story, io, issue, state, enqueue, (attempt + 1, note))] = issue
                continue
            if status == "closed":
                state["closed"].append(n)
            elif status == "blameless":
                try:
                    put_back(io, state, n, note)
                except Exception:
                    pass
            else:
                state["blocked"].append(n)
            if status == "crashed":
                for effect in (lambda: io.comment(n, f"Drain blocked: the landing queue crashed with {note}."), lambda: io.keep_open(n)):
                    try:
                        effect()
                    except Exception:
                        pass
            try:
                io.release(n)
            except Exception:
                pass

    def start_batch() -> None:
        """Hand every committed story that waits to the queue, when no batch is in flight."""
        if waiting and not landing:
            batch = [waiting.popleft() for _ in range(len(waiting))]
            landing[lander.submit(land_batch, io, batch, say)] = batch

    def step() -> None:
        """Wait for a builder or the batch to finish, and take in what finished."""
        done, _ = wait([*running, *landing], return_when=FIRST_COMPLETED)
        reap([f for f in done if f in running])
        for fut in [f for f in done if f in landing]:
            settle(fut)
        io.beat([i["number"] for i in running.values()])

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
            if closed is None:  # committed: its slot is free and the landing queue has the story (#1317)
                continue
            if closed:
                state["closed"].append(issue["number"])
            elif not any(issue["number"] in state.get(k, ()) for k in ("limited", "gone", "base", "split")):  # none of these is a failed round (#1299, #1480, #1481, #1502)
                state["blocked"].append(issue["number"])
        io.beat([i["number"] for i in running.values()])

    try:
        qa_closed = False  # the QA close waits for a board read, so a hold at start cannot skip it (#1345)
        while True:
            start_batch()  # before any hold or read failure ends the loop, so a committed story is never left waiting
            if halted():  # the stories in flight finish, then the run ends (#1480)
                if running or landing:
                    step()
                    continue
                break
            until = gh_budget.blocked_until()
            if until and until - time.time() <= HOLD_WAIT_MAX:  # a hold that ends within the hour is waited out, once (#1314)
                if running or landing:  # builders and the batch in flight finish first, and their board writes are already queued by the hold
                    step()
                    continue
                reset = time.strftime("%H:%M", time.localtime(until))
                if hold_waited:
                    state["held"] = f"GitHub's rate-limit hold was still on after the reset it named, about {reset}"
                    agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "stopped", reason=state["held"])
                    say(f"Drain stopped: {state['held']}.")
                    notify("Stopped at GitHub's limit, which is still on. Start it again later.")
                    return 1
                hold_waited = True
                notify(f"Paused for GitHub's limit. Back at about {time.strftime('%-I:%M', time.localtime(until))}.")
                agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "waiting", reason=f"GitHub's rate-limit hold lasts until about {reset}")
                say(f"Waiting for GitHub's rate-limit reset at about {reset}.")
                sleep(max(0.0, until - time.time()) + 1)
                gh_budget.replay()  # the writes queued during the hold go first
                continue
            hold_waited = False
            if not qa_closed:
                qa_closed = close_waiting_in_qa(io, say)
            issues = io.list_open()
            if issues is None:
                if running or landing:  # builders and the batch in flight settle first, so no committed story is left claimed
                    step()
                    continue
                if unread := getattr(io, "unread", ""):
                    agent_loop.log_stage(f"run-{io.repo.name}", io.repo.name, "stopped", reason=unread)
                    say(f"Drain stopped: {unread}.")
                    return 1
                say("Drain stopped: the open stories were not read.")
                return 1
            skip = set(state["closed"]) | set(state["blocked"]) | set(state.get("base", ())) | set(state.get("split", ())) | {i["number"] for i in running.values()} | set(committed)
            todo = []
            for issue in sorted((i for i in issues if i["number"] not in skip and not is_epic(i)), key=rank):
                if issue.get("status") == "Backlog" and issue["number"] not in unparked and not owner_gated(issue):  # a story parked for an overlap or a Size returns once that cause is gone (#1348)
                    unparked.add(issue["number"])
                    cause = io.parked_for(issue["number"])
                    if cause and not (cause == "size" and intake.size_of(issue) in ("L", "XL")):
                        io.set_card(issue["number"], {"status": "Ready"})
                        io.comment(issue["number"], f"{RETURNED} " + ("the drain builds stories that share files one after the other." if cause == "overlap" else f"its text Size {intake.size_of(issue)} fits one builder."))
                        issue["status"] = "Ready"
                if issue.get("status") == "Backlog" and not owner_gated(issue):  # a story that stopped before it could be split is split from Backlog (#1502)
                    n = issue["number"]
                    if n not in stuck:
                        stuck[n] = io.split_cause(issue)
                    if stuck[n]:
                        todo.append(issue)
                        continue
                why = skip_reason(issue, io.repo)
                if why == NO_AREA and issue["number"] not in filled:  # a Ready story gets its Files area once per drain, just before it builds (#1316)
                    filled.add(issue["number"])
                    if io.add_files_area(issue):
                        why = skip_reason(issue, io.repo)
                    else:
                        why += " and none could be found"
                if why:  # each skipped story is named once per drain, with the reason (#1014)
                    if owner_gated(issue):
                        skipped[issue["number"]] = "owner"
                    elif "needs splitting" in why:
                        skipped[issue["number"]] = "size"
                    if issue["number"] not in reported:
                        reported.add(issue["number"])
                        say(f"Skipped #{issue['number']}: {why}.")
                        if owner_gated(issue):
                            notify(f"#{issue['number']} needs you. The story says what to do.")
                    continue
                if re.search(r"Size:\s*(XS|S|M|L|XL)\b", issue.get("body") or "") and (text_size := intake.size_of(issue)) != str(issue["size"]).strip().upper() and issue["number"] not in mismatched:
                    mismatched.add(issue["number"])
                    say(f"#{issue['number']}: its card says Size {issue['size']} but its text says {text_size}; the card is set to {text_size} (#1342, #1348).")
                    io.set_card(issue["number"], {"size": text_size})
                if held := io.blockers(issue):  # a story waits until every blocker is closed, and the skip names the blocker (#1064)
                    skipped[issue["number"]] = "blocker"
                    if (issue["number"], tuple(held)) not in reported:
                        reported.add((issue["number"], tuple(held)))
                        say(f"Skipped #{issue['number']}: it is blocked by open {', '.join(f'#{b}' for b in held)}.")
                    continue
                skipped.pop(issue["number"], None)  # a story that starts was not skipped at the run's end
                todo.append(issue)
            state.pop("red", None)  # set again below while a red staging holds a routine story, so the run-end row can say so (#1490)
            if todo:
                counts = len(state["closed"]), len(state.get("base", ()))
                if checked != counts:  # the base is checked once per run and again after each landing (#1431) or story it held, then afresh (#1481)
                    base_red = io.base_failure(fresh=counts[1] > checked[1])
                    checked = counts
                red = "; ".join(filter(None, (base_red, io.ci_failure())))  # CI ends on its own time, so each batch of picks reads it (#1482)
                if red and red != told:
                    say(f"Staging fails validation: {red}. Only P0 stories build until it passes.")
                    if not told:
                        notify(f"Staging fails validation ({red}). Routine stories wait until staging passes.")
                told = red
                if red:
                    if any(intake.priority_of(i) != "P0" for i in todo):
                        state["red"] = red
                    todo = [i for i in todo if intake.priority_of(i) == "P0"]
            busy = [intake.files_area(i.get("body") or "") for i in [*running.values(), *committed.values()]]  # a story building, validating or landing holds its files; one overlap rule, shared with the planner (#1014)
            started = False
            for issue in todo:
                if state.get("limited") or halted() or len(running) >= io.capacity():  # no builder starts once one has hit the usage limit (#1299) or the run is halted (#1480)
                    break
                areas = intake.files_area(issue.get("body") or "")
                if any(intake.overlaps(areas, b) for b in busy) or io.claimed(issue):
                    continue
                io.claim(issue["number"], issue.get("size") or "")
                running[pool.submit(work_story, io, issue, state, enqueue)] = issue
                busy.append(areas)
                started = True
            start_batch()
            io.beat([i["number"] for i in running.values()])
            if not running and not landing:
                if todo and not started and waits < FULL_WAITS and io.capacity() == 0 and not state.get("limited"):
                    waits += 1
                    sleep(300)
                    continue
                break
            step()
    except BaseException:  # Ctrl-C or SIGTERM (#1076): the stories in flight go back to Ready and their claims go, then the stop goes on
        stopped = True
        unfinished = {i["number"]: i for i in [*running.values(), *committed.values()]}
        for fut, batch in landing.items():  # the batch in flight is waited for, so a story it lands is not put back on Ready
            try:
                rows = fut.result()
            except BaseException:
                rows = [(issue, wt, attempt, "crashed", "") for issue, wt, attempt in batch]
            for issue, _, _, status, _ in rows:
                if status == "closed":
                    unfinished.pop(issue["number"], None)
                    try:
                        io.release(issue["number"])
                    except Exception:
                        pass
        stop_builders(io, unfinished)
        say(f"Drain stopped: {len(unfinished)} building stories released to Ready. Their builders are not waited for.")
        raise
    finally:
        pool.shutdown(wait=not stopped)
        lander.shutdown(wait=not stopped)
    if state.get("limited"):
        say(f"Drain stopped for the usage limit: {agent_loop.USAGE_LIMIT_REASON}, so no new builder started.")
    say(f"Drain done: {len(state['closed'])} stories closed, {len(state['blocked'])} blocked, {state['sessions']} sessions, {state['tokens']:,} tokens.")
    return 0


def resolve_repo(name: str) -> Path | None:
    """A path, or a repo folder under repoRoot, repoRoot/_worktrees or beside OliverCode, with a readable backlog config (#1298, #1336)."""
    root = placement_config().root
    for path in (Path(name).expanduser(), root / name, root / "_worktrees" / name, OC_ROOT.parent / name):
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
    agent_loop.roll(log / f"drain-{repo.name}.log")
    with open(log / f"drain-{repo.name}.log", "a", encoding="utf-8") as out:
        spawn([sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "drain", *argv, "--foreground"], stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    print(f"Drain started for {repo.name} in its own process. Log: {out.name}. Follow it with `olivercode watch {repo.name}`.")
    return 0


def command_drain(argv: list[str], io_factory=Io, sleep=time.sleep, exit_now=os._exit, spawn=subprocess.Popen) -> int:
    """`drain REPO` runs up to the machine-wide builder limit, or N with `--parallel N` (#1055), one while the machine is heavily loaded (#1487), detached unless `--foreground` is given (#1276).
    One run holds a repo at a time (#992). When the run ends it logs one run-end row with the stories it landed and stopped. A run that ended because
    OliverCode's checkout moved logs a restarting row and starts itself again, detached, with the same repo and flags (#1480)."""
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
    code, state, ran, restart = 0, new_state(), False, False
    try:
        if not take_run(io, slug, f"drain {repo.name}"):
            return 0
        ran = True
        with run_lock.Heartbeat(slug, pid, also=getattr(io, "refresh_claims", None)):
            code = drain(io, state, sleep=sleep)
            while code == 0 and run_lock.release(slug, pid):  # a story another thread queued as this run ended is worked before the lock goes
                code = drain(io, state, sleep=sleep)
            restart = code == 0 and bool(state.get("moved")) and not state.get("limited")  # a new run would only meet the usage limit again
    except KeyboardInterrupt:  # drain has released its claims and said so; the lock goes in the finally below (#1076)
        code = 130
    finally:
        run_lock.release(slug, pid)
        if ran:
            if restart:  # before the run-end row, where `watch` stops reading
                agent_loop.log_stage(f"run-{repo.name}", repo.name, "restarting",
                                     reason=f"OliverCode moved from {state['head'][:8]} to {state['moved'][:8]}, so the drain starts again on the new code.")
            why = (f"The run stopped for the usage limit: {agent_loop.USAGE_LIMIT_REASON}." if state.get("limited")
                   else f"The run stopped: {state['held']}." if state.get("held")
                   else "The run stopped: validation calls a command that is gone." if state.get("gone")
                   else "The run was interrupted." if code == 130
                   else "The run crashed." if sys.exc_info()[0]
                   else f"The run stopped: {getattr(io, 'unread', '') or 'the open stories were not read'}." if code
                   else f"Routine stories wait because staging fails validation: {state['red']}." if state.get("red")
                   else f"Stories wait because the base branch fails validation: {next(iter(state['base'].values()))}." if state.get("base")
                   else "")  # `watch --until-exit` prints it (#1490)
            agent_loop.log_stage(f"run-{repo.name}", repo.name, "run-end", landed=len(state["closed"]), stopped=len(state["blocked"]),
                                **({"reason": why} if why else {}))
            try:
                from lib import cmd_status
                cmd_status.write_digest(slug, out=lambda _text: None)  # the digest is current when a run ends (#1313)
            except Exception as exc:  # noqa: BLE001 -- a digest bug never hides the run's end
                print(f"drain: status digest failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                io.find_bugs()
            except Exception as exc:  # noqa: BLE001 -- bug intake never hides the run's end
                print(f"drain: bug intake failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
            parked, split = set(state.get("parked", ())), set(state.get("split", ()))
            landed, retry = len(state["closed"]), len(set(state["blocked"]) - parked) + len(state.get("base", ()))
            moved = "".join(f" {len(found)} {word}." for found, word in ((split, "split"), (parked, "parked")) if found)
            started = set(state["closed"]) | split | parked
            notify(f"Done: {landed} {'story' if landed == 1 else 'stories'} landed. {retry} will try again.{moved}{skipped_summary({n: k for n, k in state['skipped'].items() if n not in started})}")
        if on_main:
            signal.signal(signal.SIGTERM, previous)
    if code == 130:  # builder threads would hold the exit until their sessions end, so a stopped run ends the process here (#1076)
        sys.stdout.flush()
        sys.stderr.flush()
        exit_now(130)
    if restart:  # the lock is gone, so the new process can take it
        return detach([a for a in argv if a != "--foreground"], repo, spawn)
    return code
