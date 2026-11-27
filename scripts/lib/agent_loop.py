"""OliverCode's own agent loop: Claude Code headless does the work, OliverCode owns the rounds around it.

The builder session runs `claude -p` on the task and exits at its commit. The runner then runs the repo's own validation directly, outside any session. A pass ends the loop. A failure starts one short fix session whose brief is the story, the diff and the last 60 lines of the gate (#888). The loop stops when validation passes, after
MAX_ROUNDS rounds, when `claude` exits with an error or when the session's token budget refuses the next call, and a stopped loop leaves the
working tree as it is. The model's tools run under the installed pretool guards, and the repo's commit gates run on every commit it makes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, model, usage_sessions, validated
from lib.local_config import OC_ROOT, setting

MAX_ROUNDS = 2  # the builder session and one short fix session (#888)
USAGE_LIMIT = re.compile(r"usage limit|\d+-hour limit|weekly limit|limit reached", re.I)  # what the CLI says when the account's allowance is spent (#1299)
USAGE_LIMIT_REASON = "Claude usage limit reached"
RESUMABLE = ("max_turns", "timeout")  # stops that leave a healthy session worth one more round (#877)
CONTINUE = "Your session stopped before you finished ({why}). Continue from where you left off, commit by explicit path and stop."
TAIL_LINES = 60
DIFF_LIMIT = 40_000
VALIDATE_TIMEOUT = 3600
DEFAULT_MODEL = "sonnet"  # builders run on Sonnet; Opus is for design judgment and cold review
LADDER = ("haiku", "sonnet", "opus")
COST_CEILING = {"XS": 1.00, "S": 2.00, "M": 4.00}  # dollars a story may spend, reader reviews included, before no further round starts (#1318); shortcut: L and XL have no ceiling, add one once their spend is measured
RESTART_ROUND = MAX_ROUNDS + 1  # a story whose last build reached this round starts its next build one level up (#1015)
READER = "sonnet"  # the least capable model that reads a commit: no story is read by anything weaker (#1015)
RISKY_FILES = ("cmd_land.py", "cmd_drain.py", "agent_loop.py", "log_action.py", "complete_story.py")  # landing, claims, gates and the loop itself (#1026)
RISKY_DIRS = ("core/hooks", "scripts/hooks")
SYSTEM = ("When you wait for a result, end your turn and never poll: every wait re-reads the whole context. Before you commit, run every test file that imports a module you changed and fix any failure. Commit by explicit path and stop: the runner runs the repo's validation and lands the commit, so run neither. A refused call says why: "
          "change your approach and never look for a way around a gate. End with one short summary.")
VERDICT_FIRST = "Your verdict is the first line of your reply, with no progress note before it."
TAKEN_BACK = re.compile(r"\bI (?:cannot|can not|can['’]t|won['’]t|will not|don['’]t|do not) (?:pass|give (?:it |this )?(?:a )?pass)\b|\bPASS is not the verdict\b", re.I)
READER_SYSTEM = ("You are a fresh reader of one story's commit. You check the story, the diff and the test output you are given, answer as the brief asks, "
                 "and change nothing. Read or search the worktree only to settle a point the diff alone cannot. " + VERDICT_FIRST)
READER_TOOLS = "Read,Grep,Glob"  # read-only, so the reader can open the file a diff calls into (#1079)
READER_TURNS = 10  # enough for a few lookups and the answer; a one-turn reader could never open a file (#1079)


NO_VALIDATION_FIX = "add scripts/validate.sh, or an npm validate or check script, and name it in the repo's CLAUDE.md."
NO_VALIDATION = f"The repo has no validation command to run. Fix: {NO_VALIDATION_FIX}"


def validation_command(cwd: str | Path) -> list[str] | None:
    """The repo's own validation command, or None when it has none this loop can run (#1012): scripts/validate.sh, then an
    `npm run NAME` that CLAUDE.md names and package.json defines, then an npm validate or check script."""
    root = Path(cwd)
    if (root / "scripts" / "validate.sh").is_file():
        return ["bash", "scripts/validate.sh"]
    try:
        scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, ValueError, AttributeError):
        return None
    try:
        text = (root / "CLAUDE.md").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    for name in re.findall(r"npm run ([\w:.-]+)", text):
        if name in scripts:
            return ["npm", "run", name]
    for name in ("validate", "check"):
        if name in scripts:
            return ["npm", "run", name]
    return None


def origin_of(path: str | Path) -> str:
    """'owner/name' of a checkout's origin remote, lower-cased, or '' when it has none."""
    ran = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True, text=True)
    url = ran.stdout.strip().removesuffix(".git") if ran.returncode == 0 else ""
    return url.replace(":", "/").split("github.com/")[-1].lower() if url else ""


def is_engine_repo(path: str | Path) -> bool:
    """True when `path` is any checkout of the repository OliverCode runs from (#1293)."""
    found = origin_of(path)
    return bool(found) and found == origin_of(OC_ROOT)


def default_branch(cwd: str | Path) -> str:
    """The branch a story starts from and lands on: the owner's engineBranch for an OliverCode checkout (#1293), else origin/HEAD, else the first of
    main, master and develop that origin holds, else main."""
    if (engine := setting("engineBranch")) and is_engine_repo(cwd):
        return engine
    ran = subprocess.run(["git", "-C", str(cwd), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], capture_output=True, text=True)
    if ran.returncode == 0 and ran.stdout.strip():
        return ran.stdout.strip().removeprefix("origin/")
    for name in ("main", "master", "develop"):
        if subprocess.run(["git", "-C", str(cwd), "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}"], capture_output=True).returncode == 0:
            return name
    return "main"


TIMED_OUT = 124  # the exit validate_gates.py gives when a run passes its time budget, and the code a runner timeout gets here (#1436)


def validate_code(cwd: str | Path) -> tuple[int, str]:
    """(exit code, the end of its output). A pass is recorded for the worktree's tree, so land reuses it and never runs the same validation again."""
    command = validation_command(cwd)
    if command is None:
        return 1, NO_VALIDATION
    try:
        ran = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=VALIDATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return TIMED_OUT, f"Validation ran past {VALIDATE_TIMEOUT} seconds and was stopped."
    if ran.returncode == 0:
        validated.record(Path(cwd))
    return ran.returncode, gate_tail(ran.stdout + ran.stderr)


def validate(cwd: str | Path) -> tuple[bool, str]:
    """(passed, the end of its output)."""
    code, tail = validate_code(cwd)
    return code == 0, tail


def gate_tail(output: str) -> str:
    """The last TAIL_LINES lines of a gate's output, which is all a fix session sees of the failure (#888)."""
    return "\n".join(output.strip().splitlines()[-TAIL_LINES:])[-6000:]


def branch_diff(cwd: str | Path) -> str:
    """The story's whole diff against origin's default branch, cut at DIFF_LIMIT characters with a marker that names the files it cut (#1015)."""
    ran = subprocess.run(["git", "-C", str(cwd), "diff", f"origin/{default_branch(cwd)}...HEAD"], capture_output=True, text=True)
    return cut_diff(ran.stdout) if ran.returncode == 0 else ""


def cut_diff(full: str) -> str:
    """The diff, or its first DIFF_LIMIT characters followed by the files the cut left unseen in full, so no reader passes a diff it did not see (#1015)."""
    if len(full) <= DIFF_LIMIT:
        return full
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"^diff --git a/(\S+) b/", full, re.M)]
    ends = [start for start, _ in starts[1:]] + [len(full)]
    unseen = [name for (_, name), end in zip(starts, ends) if end > DIFF_LIMIT]  # the file the cut lands in is partly seen, so it is named too
    which = ", ".join(unseen) if unseen else "the rest of the diff"
    return f"{full[:DIFF_LIMIT]}\n[The diff was cut at {DIFF_LIMIT} characters. The reader did not see these files in full: {which}.]\n"


def fix_brief(task: str, cwd: str | Path, tail: str) -> str:
    """The brief of the one short fix session: the story, its diff and the end of the failing gate, and nothing from the builder's session (#888)."""
    return (f"The runner validated your story's commit and a gate failed. Fix what it reports and commit by explicit path, then stop: the runner validates and lands again.\n\n"
            f"The story:\n{task}\n\nThe diff so far:\n{branch_diff(cwd)}\n\nThe last {TAIL_LINES} lines of the failing gate:\n{tail}")


def risky_paths(files) -> list[str]:
    """The Files area paths that touch landing, claims, gates or hooks (#1026): a file named in RISKY_FILES, or anything under RISKY_DIRS."""
    hits = []
    for path in files:
        name = path.rstrip("/")
        if name.rsplit("/", 1)[-1] in RISKY_FILES or any(name == d or name.startswith(d + "/") for d in RISKY_DIRS):
            hits.append(path)
    return hits


def review_mode(size: str, labels=(), files=(), priority: str = "") -> str:
    """Return the safe review lane: full for substantial or risky work, none for routine XS/S work (#1015).

    Every story still runs repository validation and commit gates. A fresh reader is required for medium-or-larger work,
    design and P0 work, and changes to the runner's safety boundary. Keeping this decision here gives every runner caller
    the same conservative policy.
    """
    names = {(l.get("name") if isinstance(l, dict) else l or "").lower() for l in labels or []}
    if size not in ("XS", "S") or "design" in names or priority == "P0" or risky_paths(files):
        return "full"
    return "none"


def route(size: str, labels=(), files=(), priority: str = "") -> tuple[str, str]:
    """(model, reason) a story starts on (#890, #1026). Only a story labeled design takes the largest. M and L take the middle. XS and S take the
    smallest unless their Files area touches landing, claims, gates or hooks, or their priority is P0, which take the middle. The reason names the rule."""
    names = {(l.get("name") if isinstance(l, dict) else l or "").lower() for l in labels or []}
    if "design" in names:
        return LADDER[-1], "labeled design"
    if size not in ("XS", "S"):
        return LADDER[1], f"size {size}"
    if risky := risky_paths(files):
        return LADDER[1], f"its Files area touches {', '.join(risky)}"
    if priority == "P0":
        return LADDER[1], "priority P0"
    return LADDER[0], f"size {size} with no risky path or P0 priority"


def escalate(model_name: str, failures: int) -> str:
    """One level up the ladder after a second failed validation, and the same model before that or when the name is not on the ladder."""
    if failures < 2 or model_name not in LADDER:
        return model_name
    return LADDER[min(LADDER.index(model_name) + 1, len(LADDER) - 1)]


def restart_model(session: str, base: str) -> str:
    """The model a story's next build starts on (#1015): one level above `base` when its last build reached RESTART_ROUND, which the run log keeps,
    so an escalation survives a restart. `base` for a story whose last build did not get that far, or whose log cannot be read. A build the reader
    failed on is left out, so the build before it still decides (#1489)."""
    reached = before = 0
    for line in run_log_lines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("story") != session:
            continue
        if row.get("review") == "none":
            reached = before
        elif isinstance(row.get("round"), int):
            if row["round"] == 1 and not row.get("resumed"):  # a new build
                before, reached = reached, 1
            else:
                reached = max(reached, row["round"])
    return escalate(base, 2) if reached >= RESTART_ROUND else base


def reader_for(builder: str) -> str:
    """The model that reads a story's commit (#1015): the builder's own model when it is Sonnet or larger, else Sonnet, so a Haiku build is never read by a weaker reader."""
    return LADDER[max(LADDER.index(READER), LADDER.index(builder) if builder in LADDER else 0)]


REVIEW_BRIEF = ("You are a fresh reader. You get the story, the diff and the test output below, and you may read and search the worktree. Check that the diff does what the "
                "story's scenarios say and breaks nothing. When the diff alone cannot settle a point, such as whether a helper it calls exists, open the file and check: a "
                "doubt you did not check is not a finding. If the diff says it was cut, read the files it names. Answer PASS on the first line "
                "when it does. Otherwise list each finding on its own line with the file and what is wrong. " + VERDICT_FIRST + "\n\nThe story:\n{task}\n\nThe diff:\n{diff}\n\nThe test output:\n{tail}")


FIX_BRIEF = ("You are a new session, not the story's builder. A fresh reader checked the story's commit and reports the findings below. Fix every finding "
             "in one commit by explicit path and stop: the runner validates and the reader reads the commit again.\n\nThe story:\n{task}\n\nThe diff so far:\n{diff}\n\nThe reader's finding:\n{finding}")


def review_brief(task: str, cwd: str | Path, finding: str) -> str:
    """The brief of the one fix session a reader's finding earns: the story, its diff and the finding, and nothing from the builder's session (#975)."""
    return FIX_BRIEF.format(task=task, diff=branch_diff(cwd), finding=finding)


def verdict_line(text: str, answers: str) -> tuple[str, str]:
    """(the verdict line, the text after it) of a reader's reply, or ('', '') when it gives none (#1477). The verdict opens the first line, or is the whole
    second line after one line of progress note. `answers` is a regex of the verdicts, matched in lower case with each run of markdown and punctuation read as one space."""
    lines = text.strip().splitlines()
    for k, i in enumerate([i for i, line in enumerate(lines) if line.strip()][:2]):
        word = re.sub(r"[^a-z0-9#]+", " ", lines[i].lower()).strip()
        if (re.fullmatch if k else re.match)(rf"(?:{answers})\b", word):
            return word, "\n".join(lines[i + 1:]).strip()
    return "", ""


def review(task: str, cwd: str | Path, session: str, tail: str, run=None, say=print, model_name: str = READER,
           max_turns: int = READER_TURNS, attempts: int = 2, brief: str = REVIEW_BRIEF) -> dict:
    """One fresh headless reader on the diff, the story and the test output (#891). Only a PASS verdict that the reply never takes back passes (#1015, #1477).
    A reader that exits non-zero or replies with nothing is asked once more, with twice the turns after a stop on the turn cap, and a second failure
    returns verdict 'none' with its cause, so nothing is pushed. Every attempt gets a run-log row (#1489).
    `brief` swaps the question: bug intake asks about a failure, not a diff (#1371).
    Returns {'verdict': 'pass' | 'findings' | 'none', 'text': str} and appends one line for it to the run log."""
    run = run or model.run_cli
    prompt = brief.format(task=task, diff=branch_diff(cwd) if "{diff}" in brief else "", tail=tail)
    failure, turns = "", max_turns
    for attempt in range(1, attempts + 1):
        try:
            reply = run(prompt, str(cwd), allowed_tools=READER_TOOLS, max_turns=turns, session=f"{session}-review", system=READER_SYSTEM, model=model_name)
        except (model.ModelError, OSError, subprocess.SubprocessError) as exc:
            failure = str(exc)
            reply = {"stop": "timeout" if isinstance(exc, model.ModelTimeout) else "", "stderr": failure}
        else:
            text = (reply.get("text") or "").strip()
            if reply.get("code", 0) == 0 and text:
                verdict = "pass" if verdict_line(text, "pass")[0] and not TAKEN_BACK.search(text) else "findings"
                log_round(f"{session}-review", attempt, model_name, reply)
                log_review(session, verdict, text)
                say(f"Review: {verdict}." + ("" if verdict == "pass" else f" {text[:300]}"))
                return {"verdict": verdict, "text": text}
            failure = exit_reason(reply, attempt, unit="attempt") if reply.get("code", 0) != 0 else "The reader replied with nothing."
        if reply.get("stop") == "max_turns":
            turns = max_turns * 2
        log_round(f"{session}-review", attempt, model_name, reply, reader_failed=True)
        say(f"Review: no verdict on attempt {attempt}. {failure}")
    log_review(session, "none", failure)
    return {"verdict": "none", "text": failure}


LOG_CAP = 262144  # bytes a log grows to before it rolls (#1429)


def roll(path: Path) -> None:
    """Move a log over LOG_CAP to its one backup `<name>.1`, so the next append starts a small live log. A log that cannot be moved is left as it is."""
    try:
        if path.stat().st_size > LOG_CAP:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def run_log_lines() -> list[str]:
    """The run log's lines, oldest first: its backup `run-log.jsonl.1` before the live log, so a roll never hides history. A part that cannot be read is skipped."""
    lines = []
    for path in (failure_log.home() / "run-log.jsonl.1", failure_log.home() / "run-log.jsonl"):
        try:
            lines += path.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
    return lines


def append_run_log(row: dict) -> None:
    """Append one JSON row to the run log, rolling it first. A log that cannot be written never stops a loop."""
    path = failure_log.home() / "run-log.jsonl"
    roll(path)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def log_review(story: str, verdict: str, text: str) -> None:
    """Append the reader's pass or findings for a story to the run log. A log that cannot be written never stops a loop."""
    append_run_log({"story": story, "review": verdict, "findings": "" if verdict == "pass" else text[:2000],
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def start_size(session_id: str, projects: Path | None = None) -> int | None:
    """The context size of a session's first call (#976): the input, cache read and cache write tokens on the first assistant line of its transcript.
    Only that line is read, so the start size costs no pass over the whole session. None when the transcript or its usage is not there."""
    path = usage_sessions.transcript(session_id, projects)
    if path is None:
        return None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    message = json.loads(line).get("message") or {}
                except (ValueError, AttributeError):
                    continue
                usage = message.get("usage") or {}
                if message.get("role") == "assistant" and usage:
                    return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    except OSError:
        return None
    return None


def log_round(story: str, n: int, model_name: str, reply: dict, start_tokens: int | None = None, why: str = "", reader_failed: bool = False) -> None:
    """Append one JSON line for a round to the run log in the OliverCode home folder: the CLI's own usage, cost, stop reason and write time, and on a session's first round the tokens it started with (#878, #987).
    A log that cannot be written never stops a loop."""
    usage = reply.get("usage") or {}
    row = {"story": story, "round": n, "model": model_name, "input": usage.get("input", 0), "output": usage.get("output", 0),
           "cache_read": usage.get("cache_read", 0), "cache_write": usage.get("cache_write", 0), "cost_usd": reply.get("cost_usd"),
           "stop": reply.get("stop", ""), "stderr_tail": reply.get("stderr", ""), "resumed": bool(reply.get("resumed")),
           "settings": reply.get("settings", ""),  # which setup ran, so the two start sizes can be compared (#911)
           "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}  # when the row was written, so a stall shows as no newer row (#987)
    if STORY_SIZE.get(story):
        row["size"] = STORY_SIZE[story]
    if reader_failed:
        row["reader_failed"] = True  # its cost is logged and counts against no ceiling (#1489)
    else:
        SPEND[story.removesuffix("-review")] = SPEND.get(story.removesuffix("-review"), 0.0) + float(reply.get("cost_usd") or 0)
    if start_tokens is not None:
        row["start_tokens"] = start_tokens
    if why:
        row["route"] = why  # the rule that chose the model the build started on (#1026)
    append_run_log(row)


STORY_SIZE: dict[str, str] = {}  # story -> its board Size, set when the drain claims it, so every later row carries it (#1301)
SPEND: dict[str, float] = {}  # story -> dollars its rounds and reader reviews have cost since the drain claimed it, across builder restarts (#1318)
STAGE_START: dict[str, float] = {}  # story -> when its current stage began, so each row says how long the stage before it took (#1291)
CITY_AT = 0.0  # when the drain last rewrote city.html (#1350)
CITY_EVERY = 60  # seconds between rewrites


def log_stage(story: str, repo: str, stage: str, started_at: float | None = None, reason: str = "", **extra) -> None:
    """Append one stage row to the run log: claimed, building, validating, landing, landed, stopped or run-end (a drain's last row, with `extra` counts). `at` is when the stage began and `seconds` is how long the
    stage before it took, counted from `started_at` (default: when this story's previous stage began). Status reads these rows for what is building (#1291)."""
    now = time.time()
    began = now if stage == "claimed" else (started_at if started_at is not None else STAGE_START.get(story, now))
    STAGE_START[story] = now
    row = {"story": story, "repo": repo, "stage": stage, "at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": int(max(0, now - began))}
    if reason:
        row["reason"] = reason[:300]
    if STORY_SIZE.get(story):
        row["size"] = STORY_SIZE[story]
    row.update(extra)
    append_run_log(row)
    refresh_city(now)


def refresh_city(now: float) -> None:
    """Rewrite city.html from local files, at most once a minute, with no GitHub or model call. A failed rewrite never stops the drain (#1350)."""
    global CITY_AT
    if now - CITY_AT < CITY_EVERY:
        return
    CITY_AT = now
    try:
        from lib import city  # local import: city reads the modules that import this one
        city.refresh(OC_ROOT)
    except Exception:  # shortcut: any failure is swallowed, since the page is a view and the next stage row retries it
        pass


def exit_reason(reply: dict, n: int, resumed: bool = False, unit: str = "round") -> str:
    """Why a round or a reader attempt ended in a non-zero exit, with the CLI's own stop reason and the tail of its stderr, so the run log and the story comment can be diagnosed (#877)."""
    why = f"claude exited {reply['code']} in {unit} {n}"
    if reply.get("stop"):
        why += f", stop reason {reply['stop']}"
    if resumed:
        why += " after one resume"
    why += "."
    tail = (reply.get("stderr") or "").strip()
    return why + (f" stderr: {tail[-300:]}" if tail else "")


def run_loop(task: str, cwd: str | Path, session: str, max_turns: int = 30, model_name: str = "", rounds: int = MAX_ROUNDS,
             run=None, check=None, say=print, why: str = "", review_mode: str = "full", repo: str = "") -> dict:
    """{'done': bool, 'reason': str, 'rounds': int, 'tokens': int, 'summary': str}, plus 'held' with the reader's finding when a second read still
    finds a problem (#975, #1015), or 'reader_failed' with the cause when the reader gave no verdict twice (#1489). Either way nothing is pushed.
    `run` and `check` default to model.run_cli and validate. `why` is the rule that chose the model, which the run log records (#1026).
    `review_mode` is `full` for the historical direct-run behavior, and the drain selects `none` for routine stories."""
    return _loop(task, cwd, session, max_turns, model_name, rounds, run, check, say, why, review_mode, repo)


def _loop(task, cwd, session, max_turns, model_name, rounds, run, check, say, why="", review_mode="full", repo="") -> dict:
    run, check = run or model.run_cli, check or (validate)
    model_name = model_name or os.environ.get("OLIVERCODE_MODEL") or DEFAULT_MODEL
    cwd, prompt, claude_session, tokens, summary = str(cwd), task, "", 0, ""
    checked = validation_command(cwd) is not None
    start, failures, findings, fix_owed, n = model_name, 0, 0, False, 0
    while n < rounds or fix_owed:  # a reader's finding is owed one fix session even after the last round (#975)
        ceiling, spent = COST_CEILING.get(STORY_SIZE.get(session, "")), SPEND.get(session, 0.0)
        if ceiling is not None and spent >= ceiling:  # the story has spent its size's ceiling, so no further round starts (#1318)
            return {"done": False, "capped": True, "reason": f"Spend ${spent:.2f} reached the ceiling of ${ceiling:.2f} for a {STORY_SIZE[session]} story, so no further round starts.",
                    "rounds": n, "tokens": tokens, "summary": summary}
        n += 1
        if repo and n > 1:
            log_stage(session, repo, "building")  # a fix round is building time again (#1291)
        fix_owed, model_name = False, escalate(start, failures)
        resumed = False
        while True:
            try:
                reply = run(prompt, cwd, max_turns=max_turns, session=session, system=SYSTEM, model=model_name, resume=claude_session)
            except model.ModelTimeout as exc:  # the session survives a timeout, so it is resumed once (#877)
                log_round(session, n, model_name, {"stop": "timeout", "stderr": str(exc), "resumed": resumed}, why=why)
                if resumed or not exc.session_id:
                    return {"done": False, "reason": f"{exc} It was resumed once and ran past the limit again." if resumed else str(exc),
                            "rounds": n, "tokens": tokens, "summary": summary}
                say(f"Round {n}: {exc} Resuming the same session once.")
                claude_session, prompt, resumed = exc.session_id, CONTINUE.format(why="it ran past the time limit"), True
                continue
            except (model.ModelError, OSError, subprocess.SubprocessError) as exc:
                return {"done": False, "reason": str(exc), "rounds": n - 1, "tokens": tokens, "summary": summary}
            reply = {**reply, "resumed": resumed}
            tokens += reply["tokens"]
            claude_session = reply["session_id"] or claude_session
            log_round(session, n, model_name, reply, start_size(reply["session_id"]) if n == 1 and not resumed else None, why=why)
            summary = reply["text"]
            say(f"Round {n}: {summary.strip()[:300]}")
            if reply["code"] != 0 and USAGE_LIMIT.search(f"{reply['text']}\n{reply.get('stderr') or ''}"):  # a restart would hit the same limit (#1299)
                return {"done": False, "usage_limit": True, "reason": f"{USAGE_LIMIT_REASON}: {exit_reason(reply, n, resumed)}",
                        "rounds": n, "tokens": tokens, "summary": summary}
            if reply["code"] != 0 and reply.get("stop") in RESUMABLE and not resumed and claude_session:
                say(f"Round {n}: claude stopped on {reply['stop']}. Resuming the same session once.")
                prompt, resumed = CONTINUE.format(why=f"the CLI stopped on {reply['stop']}"), True
                continue
            break
        if reply["code"] != 0:
            return {"done": False, "reason": exit_reason(reply, n, resumed), "rounds": n, "tokens": tokens, "summary": summary}
        if not checked:
            return {"done": False, "reason": f"The model finished, but nothing checked the result. {NO_VALIDATION}", "fatal": True,
                    "rounds": n, "tokens": tokens, "summary": summary}
        if validation_command(cwd) is None and not Path(cwd).exists():  # the builder landed the story and its worktree is gone, so there is nothing left to validate (#877)
            return {"done": True, "reason": "The story landed during the round, so its worktree is gone and validation is skipped.",
                    "rounds": n, "tokens": tokens, "summary": summary}
        if repo:
            log_stage(session, repo, "validating")
        passed, tail = check(cwd)
        if passed:
            if review_mode == "none":
                return {"done": True, "reason": "The repo's validation passes; routine story review is covered by validation and commit gates.",
                        "rounds": n, "tokens": tokens, "summary": summary}
            verdict = review(task, cwd, session, tail, run=run, say=say, model_name=reader_for(model_name),
                             max_turns=READER_TURNS, attempts=2)
            if verdict["verdict"] == "none":  # the reader failed twice, so nothing lands, and its failure is no finding (#1015, #1489)
                return {"done": False, "reader_failed": verdict["text"], "reason": f"The reader failed, so nothing is pushed: {verdict['text']}",
                        "rounds": n, "tokens": tokens, "summary": summary}
            if verdict["verdict"] == "findings":
                findings += 1
                if findings == 1:  # one fix session, then the reader reads again (#975)
                    say(f"Round {n}: the reader found a problem. One fix session, then the reader reads again.")
                    prompt, claude_session, fix_owed = review_brief(task, cwd, verdict["text"]), "", True
                    continue
                return {"done": False, "held": verdict["text"], "reason": f"The fresh reader reports a problem, so nothing is pushed: {verdict['text'][:300]}",
                        "rounds": n, "tokens": tokens, "summary": summary}
            return {"done": True, "reason": "The repo's validation passes.", "rounds": n, "tokens": tokens, "summary": summary}
        failures += 1
        say(f"Round {n}: validation failed.")
        prompt, claude_session = fix_brief(task, cwd, tail), ""  # a fresh session: the builder's context and its expired cache are not carried over (#888)
    return {"done": False, "reason": f"Validation still failed after {rounds} rounds. The tree is as the last round left it.",
            "rounds": rounds, "tokens": tokens, "summary": summary}
