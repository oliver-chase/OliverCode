"""A step the permission classifier denied reaches the owner queue once, with its exact command (#781, #787).

`scripts/hooks/denial_watch.py` passes each Bash command and its output to `record`. A denial of a persistent job
(a launchd load, `olivercode maintain --schedule`) queues one line with the job label and the command to paste. `resolved`
is the check that closes a line once the owner ran the command. Standard library only.
"""

from __future__ import annotations

import os
import re
import subprocess

from lib import cmd_owner

DENIED = re.compile(r"permission[^\n]{0,80}denied|denied[^\n]{0,80}(?:permission|classifier)|classifier[^\n]{0,80}(?:denied|blocked)", re.IGNORECASE)
SESSION = "denied-step"
JOB = re.compile(r"\blaunchctl\s+(?:bootstrap|load|enable|kickstart)\b|\bolivercode\b[^\n]*--schedule\b")
GIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(push|merge|reset\s+--hard|rebase\s+--abort)\b")
LABEL = re.compile(r"([A-Za-z][\w.-]*\.[\w.-]+?)(?:\.plist)?(?:\s|$)")


def is_denied(output: str) -> bool:
    return bool(DENIED.search(output))


def _run(*args: str) -> str:
    try:
        done = subprocess.run(list(args), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def job_label(command: str) -> str:
    """The launchd label a denied command loads: the plist name or the label it names, else the command's own `--schedule` job."""
    for word in reversed(command.split()):
        found = LABEL.match(os.path.basename(word.strip("'\"")) + " ")
        if found and "." in found.group(1) and not word.startswith("-"):
            return found.group(1)
    found = re.search(r"olivercode\s+(\w[\w-]*)[^\n]*--schedule", command)
    return f"olivercode.{found.group(1)}" if found else ""


def classify(command: str, cwd: str) -> tuple[str, str, str, dict] | None:
    """(key, step, command, resolve) for a command the classifier can deny, or None for any other command."""
    if JOB.search(command):
        label = job_label(command) or "a persistent job"
        return (f"job:{label}", f"Load the job {label}: it keeps running on its schedule once it is loaded", command,
                {"kind": "job", "label": label})
    git = GIT.search(command)
    if git:
        verb = " ".join(git.group(1).split())
        return (f"git:{verb}:{cwd}", f"Run git {verb} in {cwd or 'the repo'}: the classifier denied it and it changes the repo", command,
                {"kind": "manual"})
    return None


def record(command: str, output: str, session: str = "", cwd: str = "") -> dict | None:
    """Queue the denied command once. Returns the new owner-queue line, or None when the output holds no denial, the command is not
    one the queue covers, or its line is already open."""
    if not is_denied(output):
        return None
    found = classify(command, cwd)
    if not found:
        return None
    key, step, cmd, resolve = found
    error = next((ln.strip() for ln in output.splitlines() if DENIED.search(ln)), "denied by the permission classifier")[:300]
    try:
        return cmd_owner.queue_denied(session or SESSION, key, step, cmd, error, resolve)
    except ValueError:
        return None


def resolved(item: dict) -> bool:
    """True when the check on a queued line shows the owner ran its command."""
    check = item.get("resolve") or {}
    if check.get("kind") == "job":
        return bool(_run("launchctl", "print", f"gui/{os.getuid()}/{check.get('label', '')}"))
    return False


def close_resolved() -> int:
    """Close every open denied-step line whose check passes. Returns how many closed."""
    done = 0
    for item in cmd_owner.items():
        if item["status"] == "open" and item.get("resolve") and resolved(item):
            cmd_owner.close(item["id"])
            done += 1
    return done
