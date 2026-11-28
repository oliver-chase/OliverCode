#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: a status question is answered from the status digest, with no model turn (#991, #1000).

When the owner's prompt asks what is building, what is left or when something finishes, the hook reads the board line and the open stories from
status-digest.md (cmd_status.digest_path). A message that is only a status question is blocked when the digest is fresh, and those lines are the block reason, so no model
turn runs and the message never enters the thread. A mixed message goes through with the lines added as context. Every other prompt, a prompt that
starts with "ask:", and every message from another session or a notification, gets nothing. The hook fails open on its own error.

It numbers a new OliverCode chat (#1488): on the first prompt of an interactive session that starts in a checkout of the OliverCode repo or names OliverCode, it
records the next thread number and gives the calls that title and pin the session. A `handoff read` prompt is left to that command, which numbers its thread.

It also flags a long thread once (#1319): when an interactive session's transcript shows over 250,000 tokens of context, the first prompt after that
gets one line telling the session to write the handoff with `olivercode handoff write`, which prints the calls that start the next thread (#1321, #1488).
A marker in the OliverCode home keeps it to once per session, and a headless builder is never flagged.

A thread over 300,000 tokens takes no new work until it writes that handoff (#1519): until a PROJECT-handoff file in the session's folder is newer than
the marker, the owner's prompt is blocked unless it names the handoff or starts with "ask:", and one that does goes through with a note that the turn
writes the handoff. A headless builder is never blocked.

It names each story the drain handed back (#1532): the owner's next prompt in an interactive OliverCode chat gets one line per open owner-queue item that
names a story, with its number, title and stop reason. A marker in the OliverCode home keeps it to once per item, and a status-only prompt that would
carry such a line goes through instead of being blocked. In a thread the 300,000-token block would stop, it is answered from the digest and the item stays unshown.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import failure_log  # noqa: E402
from lib import cmd_owner, cmd_status, gh_budget  # noqa: E402

STALE_SECONDS = 3600  # a digest older than this is labeled with its age
LONG_TOKENS = 250_000  # a thread past this re-reads more cached context per turn than the turn's work costs (#1319)
BLOCK_TOKENS = 300_000  # a thread past this ignored the note above, so it takes only the handoff (#1519)
TAIL_BYTES = 1_000_000  # the last model call's usage is near the end of the transcript
STOPS_PER_PROMPT = 3  # each new story costs one title read, so the rest wait for the next prompt and the hook stays inside its timeout
CHARS = 1200 # the board line and the open list, about three hundred tokens, is what a status answer needs
FOLLOW = ("`olivercode watch REPO` prints each story's stage live with its time, tokens and API-price equivalent, at no model cost.\n"  # how the owner follows a run (#1518)
          "`olivercode status` shows the open count, pace and what is next, at no model cost.")
HANDOFF_CALLS = ("run `olivercode handoff write PROJECT FILE` and make the calls it prints, which start the next thread in the desktop app. "
                 "Start no other session. Tell the owner in one line.")
# A question about the board only: "status" alone, or "status" in a question or a status-of phrase. "the PR status is red" and "add a status field" are not questions.
STATUS_RE = re.compile(r"\bwhat(?:'s| is| are)\s+(?:the\s+)?status\b|\bstatus\s+(?:of|on)\b|^\s*(?:any\s+|the\s+)?status\s*\??\s*$"
                       r"|\bwhat(?:'s| is| are)\s+(?:still\s+)?(?:building|left|running|in progress|open)\b|\bhow far\b"
                       r"|\bwhen\s+(?:will|is|does)\s+(?:it|this|that|everything|the\s+\w+)\s+(?:finish|land|complete|be\s+done|be\s+ready|done|ready)\b",
                       re.IGNORECASE | re.MULTILINE)
ASK_RE = re.compile(r"\s*ask:", re.IGNORECASE)  # the owner's way to force a model turn on a status question
OC_ROOT = Path(__file__).resolve().parents[2]
NAMES_OC_RE = re.compile(r"\bolivercode\b", re.IGNORECASE)
NAMES_HANDOFF_RE = re.compile(r"\bhand[\s-]?off", re.IGNORECASE)
HANDOFF_READ_RE = re.compile(r"""olivercode['"]?\s+handoff\s+read\b""", re.IGNORECASE)  # the launcher path may be quoted
# Words that may remain once the status phrase is cut out: a message that leaves any other word, such as "and fix the parser", also asks for work.
FILLER = {"a", "about", "along", "and", "any", "are", "board", "done", "far", "finish", "how", "i", "is", "it", "left", "now", "of", "on", "please",
          "queue", "ready", "right", "so", "still", "status", "that", "the", "this", "thanks", "what", "when", "whats", "will", "you", "everything"}
WORD_RE = re.compile(r"[a-z']+")


# A prompt that starts like this came from another session or the system, so the owner did not type it.
SKIP_PREFIXES = ("<cross-session-message", "[cross-session-message", "<system-notification", "[system-notification",
                 "system-notification:", "<system-reminder", "<task-notification", "<side-sessions-event", "<ci-monitor-event",
                 "[system notification", "another claude session sent a message", "<agent-message", "[subagent hand-back]",
                 "<scheduled-task", "background (from the session that started this one)")


def from_owner(prompt: str) -> bool:
    """True when the owner typed the prompt: it is not a message from another session, a notification or a hand-back."""
    text = (prompt or "").lstrip().lower()
    return bool(text) and not text.startswith(SKIP_PREFIXES) and "another claude session sent a message" not in text[:300]


def is_status_question(prompt: str) -> bool:
    return from_owner(prompt) and not ASK_RE.match(prompt) and bool(STATUS_RE.search(prompt))


def is_status_only(prompt: str) -> bool:
    """True when the prompt is a status question and nothing else: every word left after the status phrase is filler."""
    if not is_status_question(prompt):
        return False
    return all(word in FILLER for word in WORD_RE.findall(STATUS_RE.sub(" ", prompt).lower()))


def open_part(text: str) -> str:
    """The digest from its title through the open stories, before the landed section, at most CHARS characters."""
    head, _, _ = text.partition("\n## Landed")
    return head.strip()[:CHARS]


def age_note(path: Path, now: float | None = None) -> str:
    """'' for a digest written within the hour, else how old it is and that `olivercode status` gives the current figures (#1313)."""
    try:
        age = (now or time.time()) - path.stat().st_mtime
    except OSError:
        return ""
    if age <= STALE_SECONDS:
        return ""
    hours = int(age // 3600)
    old = f"{hours // 24} days" if hours >= 48 else f"{hours} hours"
    return f"This digest is {old} old. Run `olivercode status` for the current figures.\n"


def context(prompt: str, path: Path | None = None) -> str:
    """The digest's board and open lines for a status question, or '' for any other prompt."""
    if not is_status_question(prompt):
        return ""
    path = path or cmd_status.digest_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Say so and offer to write it with `olivercode status digest`."
    stale = age_note(path)
    if stale:  # a stale digest gives no figures, so none can be recalled (#1329)
        return f"The status digest at {path} is stale, so none of its figures are given. {stale}Run `olivercode status` before answering."
    written = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(path.stat().st_mtime))
    return (f"Status from the status file {path}, written {written}:\n{open_part(text)}\n"
            f"Confirm any figure your answer gives with a command before stating it. The full status file is {path}, and the owner can read it there.\n"
            f"End your answer with these two lines:\n{FOLLOW}")


def context_tokens(transcript: Path) -> int:
    """The context size at the transcript's last model call: its input, cache-read and cache-write tokens, or 0 when none can be read (#1319)."""
    try:
        with transcript.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))  # shortcut: reads only the tail, so a final record over TAIL_BYTES reads as 0; upgrade if usage lines grow that large
            lines = handle.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        try:
            usage = json.loads(line).get("message", {}).get("usage")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(usage, dict):
            return sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def interactive_session(data: dict) -> str:
    """The session's id, or '' for a headless builder or input with no id."""
    if os.environ.get("OLIVERCODE_HEADLESS") == "1":  # model.HEADLESS_ENV
        return ""
    return re.sub(r"[^\w-]", "", str(data.get("session_id") or ""))


def shared_git_dir(folder: str) -> str:
    """The .git folder a checkout shares with its worktrees, or '' outside a repo."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}  # an inherited GIT_DIR would answer for every folder
    done = subprocess.run(["git", "-C", folder, "rev-parse", "--path-format=absolute", "--git-common-dir"], env=env,
                          capture_output=True, text=True, timeout=3)
    return done.stdout.strip() if done.returncode == 0 else ""


def in_olivercode(folder: str) -> bool:
    """Whether `folder` is in any checkout of the repo this hook runs from, which may itself be a worktree."""
    found = shared_git_dir(folder) if folder else ""
    return bool(found) and found == shared_git_dir(str(OC_ROOT))


def new_thread_note(data: dict) -> str:
    """The calls that number and pin a new OliverCode chat (#1488), or ''. Only a first prompt counts, so a later mention never takes the pin."""
    prompt, session = str(data.get("prompt") or ""), interactive_session(data)
    if not session or not from_owner(prompt) or HANDOFF_READ_RE.search(prompt):
        return ""
    if context_tokens(Path(str(data.get("transcript_path") or ""))):  # a model call is on record, so this is not the first prompt
        return ""
    if not (NAMES_OC_RE.search(prompt) or in_olivercode(str(data.get("cwd") or ""))):
        return ""
    from lib import cmd_handoff  # imported only for a new OliverCode chat, not on every prompt
    number, steps = cmd_handoff.claim_thread("OliverCode", session)
    if not steps:
        return ""
    return f"This is a new OliverCode chat, thread {number}. Make these calls before the turn's work:\n" + "\n".join(steps)


def handoff_since(folder: str, since: float) -> bool:
    """Whether the folder `olivercode handoff write` files into for this session holds a handoff newer than `since`."""
    found = Path(os.environ.get("OLIVERCODE_HANDOFF_DIR") or folder or ".").expanduser().glob("*-handoff-*.md")
    return any(path.is_file() and path.stat().st_mtime > since for path in found)


def long_thread(data: dict) -> tuple[str, str]:
    """(block reason, context line) for a long interactive thread, each '' when it does not apply, and both '' for a short thread or a headless builder.

    Past LONG_TOKENS the line comes once per session. Past BLOCK_TOKENS, until a handoff is newer than the marker, the owner's prompt is blocked,
    or gets the handoff-turn line when it names the handoff or starts with "ask:"."""
    session = interactive_session(data)
    transcript = str(data.get("transcript_path") or "")
    if not session or not transcript:
        return "", ""
    tokens = context_tokens(Path(transcript))
    if tokens < LONG_TOKENS:
        return "", ""
    marker = failure_log.home() / f"long-thread-{session}"
    first = not marker.exists()
    if first:
        marker.touch()
    prompt = str(data.get("prompt") or "")
    if tokens > BLOCK_TOKENS and from_owner(prompt):
        if handoff_since(str(data.get("cwd") or ""), marker.stat().st_mtime):
            return "", ""
        if ASK_RE.match(prompt) or NAMES_HANDOFF_RE.search(prompt):
            return "", f"This thread's context is past 300,000 tokens, so this turn writes the handoff and takes no other work: {HANDOFF_CALLS}"
        return ('This thread is past 300,000 tokens of context, so it takes no new work until its handoff is written. Type "handoff" so this '
                "session writes it with `olivercode handoff write`."), ""
    if not first:
        return "", ""
    return "", ("This thread's context is past 250,000 tokens, so each turn costs more than the work in it. When this turn's work is done, "
                f"{HANDOFF_CALLS} The owner never has to ask for a handoff.")


def handed_back(data: dict) -> list[tuple[Path, dict]]:
    """(marker, item) for each open owner-queue story no chat has shown, or [] unless the owner typed the prompt in an interactive OliverCode chat (#1532)."""
    session = interactive_session(data)
    if not session or not from_owner(str(data.get("prompt") or "")):
        return []
    marked = ((failure_log.home() / f"owner-shown-{item['id']}", item) for item in cmd_owner.open_items() if item.get("story"))
    new = [(marker, item) for marker, item in marked if not marker.exists()]
    if not new or in_olivercode(str(data.get("cwd") or "")):
        return new[:STOPS_PER_PROMPT]
    from lib import cmd_handoff  # a numbered OliverCode chat counts wherever it runs
    numbered = cmd_handoff.stored(cmd_handoff.THREAD_SESSIONS).get("sessions", {}).get(session, {})
    return new[:STOPS_PER_PROMPT] if "OliverCode" in numbered else []


def story_title(item: dict) -> str:
    """The story's title, read over REST from the repo the item's key names, or '' when it cannot be read."""
    slug = re.search(r":([\w.-]+/[\w.-]+)#\d+$", str(item.get("key") or ""))
    if not slug or gh_budget.refusal("rest"):
        return ""
    try:
        done = subprocess.run(["gh", "api", f"repos/{slug[1]}/issues/{item['story']}", "--jq", ".title"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def stop_note(data: dict) -> str:
    """One line per newly handed-back story, each marked shown, or ''."""
    found = [(marker, item, story_title(item)) for marker, item in handed_back(data)]
    lines = []
    for marker, item, title in found:  # marked after every title read, so a hook cut off during a read marks nothing
        try:
            marker.touch(exist_ok=False)
        except FileExistsError:  # another chat's prompt showed it first
            continue
        reason = str(item.get("step") or "").removeprefix(f"Story #{item['story']} waits on you: ")
        named = f'"{cmd_status._text(title)}"' if title else "(title not read)"
        lines.append(f"Tell the owner the drain handed back story #{item['story']} {named}. Stop reason: {cmd_status._text(reason, 300)}")
    return "\n".join(lines)


def block_reason(path: Path) -> str:
    """The reason shown to the owner when a status-only prompt is blocked: the digest's lines and the two commands that follow a run, or a note that none is written yet."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"No status digest is written yet at {path}. Write it with `olivercode status digest`."
    return f"Status from the status file {path}:\n{open_part(text)}\n{FOLLOW}"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    prompt = str(data.get("prompt") or "")
    # A status-only prompt over a stale digest goes through to the session instead of being answered from old figures (#1329).
    # So does one with a handed-back story to name, since a block adds no line to the chat, unless the long thread would block it anyway (#1532).
    status_only = is_status_only(prompt) and not age_note(cmd_status.digest_path())
    carries = status_only and bool(handed_back(data))
    reason, long_note = long_thread(data) if carries or not status_only else ("", "")
    if status_only and (reason or not carries):
        # The block ends the turn, so the context beside it is never read; it keeps the #991 output shape for a status-only prompt.
        print(json.dumps({"decision": "block", "reason": block_reason(cmd_status.digest_path()),
                          "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context(prompt)}}))
        return 0
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    # stop_note comes last: it sees a chat new_thread_note just numbered, and marks nothing shown if an earlier part fails.
    text = "\n".join(part for part in (context(prompt), new_thread_note(data), long_note, stop_note(data)) if part)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- a broken check must never stop the owner's prompt
        print(f"status_hint failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
