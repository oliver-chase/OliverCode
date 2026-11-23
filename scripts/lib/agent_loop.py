"""OliverCode's own agent loop: Claude Code headless does the work, OliverCode owns the rounds around it.

The builder session runs `claude -p` on the task and exits at its commit. The runner then runs the repo's own validation through the
per-user queue, outside any session. A pass ends the loop. A failure starts one short fix session whose brief is the story, the diff and the last 60 lines of the gate (#888). The loop stops when validation passes, after
MAX_ROUNDS rounds, when `claude` exits with an error or when the session's token budget refuses the next call, and a stopped loop leaves the
working tree as it is. The model's tools run under the installed pretool guards, and the repo's commit gates run on every commit it makes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lib import failure_log, model
from lib.local_config import OC_ROOT

MAX_ROUNDS = 2  # the builder session and one short fix session (#888)
RESUMABLE = ("max_turns", "timeout")  # stops that leave a healthy session worth one more round (#877)
CONTINUE = "Your session stopped before you finished ({why}). Continue from where you left off, commit by explicit path and stop."
TAIL_LINES = 60
DIFF_LIMIT = 40_000
VALIDATE_TIMEOUT = 3600
DEFAULT_MODEL = "sonnet"  # builders run on Sonnet; Opus is for design judgment and cold review
LADDER = ("haiku", "sonnet", "opus")
SYSTEM = ("When you wait for a result, end your turn and never poll: every wait re-reads the whole context. Commit by explicit path and stop: the runner runs the repo's validation and lands the commit, so run neither. A refused call says why: "
          "change your approach and never look for a way around a gate. End with one short summary.")


def validation_command(cwd: str | Path) -> list[str] | None:
    """The repo's own validation command, or None when it has none this loop can run."""
    if (Path(cwd) / "scripts" / "validate.sh").is_file():
        return ["bash", "scripts/validate.sh"]
    return None


def validate(cwd: str | Path) -> tuple[bool, str]:
    """(passed, the end of its output). It waits for a slot in the per-user validation queue."""
    command = validation_command(cwd)
    if command is None:
        return False, "The repo has no validation command to run."
    argv = [sys.executable, str(OC_ROOT / "scripts" / "olivercode"), "queue", "run", "--", *command]
    try:
        ran = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=VALIDATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"Validation ran past {VALIDATE_TIMEOUT} seconds and was stopped."
    return ran.returncode == 0, gate_tail(ran.stdout + ran.stderr)


def gate_tail(output: str) -> str:
    """The last TAIL_LINES lines of a gate's output, which is all a fix session sees of the failure (#888)."""
    return "\n".join(output.strip().splitlines()[-TAIL_LINES:])[-6000:]


def branch_diff(cwd: str | Path) -> str:
    """The story's whole diff against origin's default branch, cut at DIFF_LIMIT characters."""
    for base in ("origin/main", "origin/master"):
        ran = subprocess.run(["git", "-C", str(cwd), "diff", f"{base}...HEAD"], capture_output=True, text=True)
        if ran.returncode == 0:
            return ran.stdout[:DIFF_LIMIT]
    return ""


def fix_brief(task: str, cwd: str | Path, tail: str) -> str:
    """The brief of the one short fix session: the story, its diff and the end of the failing gate, and nothing from the builder's session (#888)."""
    return (f"The runner validated your story's commit and a gate failed. Fix what it reports and commit by explicit path, then stop: the runner validates and lands again.\n\n"
            f"The story:\n{task}\n\nThe diff so far:\n{branch_diff(cwd)}\n\nThe last {TAIL_LINES} lines of the failing gate:\n{tail}")


def model_for(size: str, labels=()) -> str:
    """The model a story starts on (#890): XS and S the smallest, M and L the middle, and only a story labeled design the largest."""
    names = {(l.get("name") if isinstance(l, dict) else l or "").lower() for l in labels or []}
    if "design" in names:
        return LADDER[-1]
    return LADDER[0] if size in ("XS", "S") else LADDER[1]


def escalate(model_name: str, failures: int) -> str:
    """One level up the ladder after a second failed validation, and the same model before that or when the name is not on the ladder."""
    if failures < 2 or model_name not in LADDER:
        return model_name
    return LADDER[min(LADDER.index(model_name) + 1, len(LADDER) - 1)]


REVIEW_BRIEF = ("You are a fresh reader. You see only the story, the diff and the test output below, and you make no tool call. Check that the diff does what the story's "
                "scenarios say and breaks nothing the diff itself shows. Answer PASS on the first line when it does. Otherwise list each finding on its own line "
                "with the file and what is wrong.\n\nThe story:\n{task}\n\nThe diff:\n{diff}\n\nThe test output:\n{tail}")


def review(task: str, cwd: str | Path, session: str, tail: str, run=None, say=print) -> dict:
    """One fresh headless reader on the diff, the story and the test output (#891). Returns {'verdict': 'pass' | 'findings' | 'none', 'text': str}
    and appends one line for it to the run log. A reader that fails never stops a landing."""
    run = run or model.run_cli
    prompt = REVIEW_BRIEF.format(task=task, diff=branch_diff(cwd), tail=tail)
    try:
        reply = run(prompt, str(cwd), allowed_tools="Read", max_turns=1, session=f"{session}-review", system=SYSTEM, model="sonnet")
    except (model.ModelError, OSError, subprocess.SubprocessError) as exc:
        say(f"Review: no reader ran. {exc}")
        return {"verdict": "none", "text": str(exc)}
    text = (reply.get("text") or "").strip()
    verdict = "pass" if text.upper().startswith("PASS") else "findings" if text else "none"
    log_round(f"{session}-review", 1, "sonnet", reply)
    log_review(session, verdict, text)
    say(f"Review: {verdict}." + ("" if verdict == "pass" else f" {text[:300]}"))
    return {"verdict": verdict, "text": text}


def log_review(story: str, verdict: str, text: str) -> None:
    """Append the reader's pass or findings for a story to the run log. A log that cannot be written never stops a loop."""
    try:
        with open(failure_log.home() / "run-log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"story": story, "review": verdict, "findings": "" if verdict == "pass" else text[:2000]}) + "\n")
    except OSError:
        pass


def log_round(story: str, n: int, model_name: str, reply: dict, start_tokens: int | None = None) -> None:
    """Append one JSON line for a round to the run log in the OliverCode home folder: the CLI's own usage, cost and stop reason, and on a session's first round the tokens it started with (#878).
    A log that cannot be written never stops a loop."""
    usage = reply.get("usage") or {}
    row = {"story": story, "round": n, "model": model_name, "input": usage.get("input", 0), "output": usage.get("output", 0),
           "cache_read": usage.get("cache_read", 0), "cache_write": usage.get("cache_write", 0), "cost_usd": reply.get("cost_usd"),
           "stop": reply.get("stop", ""), "stderr_tail": reply.get("stderr", ""), "resumed": bool(reply.get("resumed")),
           "settings": reply.get("settings", "")}  # which setup ran, so the two start sizes can be compared (#911)
    if start_tokens is not None:
        row["start_tokens"] = start_tokens
    try:
        with open(failure_log.home() / "run-log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def exit_reason(reply: dict, n: int, resumed: bool = False) -> str:
    """Why a round ended in a non-zero exit, with the CLI's own stop reason and the tail of its stderr, so the run log and the story comment can be diagnosed (#877)."""
    why = f"claude exited {reply['code']} in round {n}"
    if reply.get("stop"):
        why += f", stop reason {reply['stop']}"
    if resumed:
        why += " after one resume"
    why += "."
    tail = (reply.get("stderr") or "").strip()
    return why + (f" stderr: {tail[-300:]}" if tail else "")


def run_loop(task: str, cwd: str | Path, session: str, max_turns: int = 30, model_name: str = "", rounds: int = MAX_ROUNDS,
             run=None, check=None, say=print, size: str = "") -> dict:
    """{'done': bool, 'reason': str, 'rounds': int, 'tokens': int, 'summary': str}. `run` and `check` default to model.run_cli and validate."""
    return _loop(task, cwd, session, max_turns, model_name, rounds, run, check, say, size)


def _loop(task, cwd, session, max_turns, model_name, rounds, run, check, say, size) -> dict:
    run, check = run or model.run_cli, check or validate
    model_name = model_name or os.environ.get("OLIVERCODE_MODEL") or DEFAULT_MODEL
    cwd, prompt, claude_session, tokens, summary = str(cwd), task, "", 0, ""
    checked = validation_command(cwd) is not None
    start, failures = model_name, 0
    for n in range(1, rounds + 1):
        model_name = escalate(start, failures)
        resumed = False
        while True:
            try:
                reply = run(prompt, cwd, max_turns=max_turns, session=session, system=SYSTEM, model=model_name, resume=claude_session)
            except model.ModelTimeout as exc:  # the session survives a timeout, so it is resumed once (#877)
                log_round(session, n, model_name, {"stop": "timeout", "stderr": str(exc), "resumed": resumed})
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
            log_round(session, n, model_name, reply, (reply.get("usage") or {}).get("cache_write", 0) if n == 1 and not resumed else None)
            summary = reply["text"]
            say(f"Round {n}: {summary.strip()[:300]}")
            if reply["code"] != 0 and reply.get("stop") in RESUMABLE and not resumed and claude_session:
                say(f"Round {n}: claude stopped on {reply['stop']}. Resuming the same session once.")
                prompt, resumed = CONTINUE.format(why=f"the CLI stopped on {reply['stop']}"), True
                continue
            break
        if reply["code"] != 0:
            return {"done": False, "reason": exit_reason(reply, n, resumed), "rounds": n, "tokens": tokens, "summary": summary}
        if not checked:
            return {"done": False, "reason": "The model finished, but the repo has no scripts/validate.sh, so nothing checked the result.",
                    "rounds": n, "tokens": tokens, "summary": summary}
        if validation_command(cwd) is None:  # the builder landed the story and its worktree is gone, so there is nothing left to validate (#877)
            return {"done": True, "reason": "The story landed during the round, so its worktree is gone and validation is skipped.",
                    "rounds": n, "tokens": tokens, "summary": summary}
        passed, tail = check(cwd)
        if passed:
            from lib import cmd_land  # land imports this module's neighbours, so the import waits until a story passes
            if cmd_land.needs_review(size, cmd_land.changed_paths(Path(cwd))):
                review(task, cwd, session, tail, run=run, say=say)
            return {"done": True, "reason": "The repo's validation passes.", "rounds": n, "tokens": tokens, "summary": summary}
        failures += 1
        say(f"Round {n}: validation failed.")
        prompt, claude_session = fix_brief(task, cwd, tail), ""  # a fresh session: the builder's context and its expired cache are not carried over (#888)
    return {"done": False, "reason": f"Validation still failed after {rounds} rounds. The tree is as the last round left it.",
            "rounds": rounds, "tokens": tokens, "summary": summary}
