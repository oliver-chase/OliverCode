"""A tracked permission policy per repo, enforced before an agent acts.

`.olivercode/policy.json` lists the commands and paths an agent may use and the moments it must
stop and ask. `scripts/hooks/policy_guard.py` calls `evaluate_bash` and `evaluate_path` on every
Bash, Edit and Write call, and each deny or ask is written to the failure log. A repo with no
policy file is not restricted, and `olivercode health` reports it.

Standard library only: the hook runs on every tool call.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

POLICY_FILE = ".olivercode/policy.json"
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "sudo", "time", "nice", "timeout"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATOR_CHARS = ";&|()\n"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

DEFAULT = {
    "version": 1,
    "commands": {
        "allow": ["git", "gh", "python3", "python", "bash", "sh", "zsh", "ls", "cat", "grep", "rg", "sed", "awk",
                  "find", "head", "tail", "wc", "sort", "uniq", "diff", "cmp", "mkdir", "cp", "mv", "rm", "touch",
                  "echo", "printf", "cd", "pwd", "test", "jq", "date", "sleep", "xargs", "chmod", "ln", "readlink",
                  "dirname", "basename", "du", "df", "ps", "lsof", "tee", "tr", "cut", "node", "npm", "npx",
                  "pytest", "make", "true", "false", "export", "set", "source", "unset", "[", "[[", "if", "for",
                  "while", "do", "done", "then", "fi", "else", "case", "esac", "in", "time", "tar", "mktemp"],
        "deny": [r"git\s+push\s+.*--force", r"git\s+push\s+.*\s-f(\s|$)", r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$)",
                 r"curl\s+.*\|\s*(ba|z)?sh"],
    },
    "paths": {
        "allow": ["**"],
        "deny": [".git/**", ".env", ".env.*", ".secrets/**", ".githooks/**"],
    },
    "triggers": {"gateFailures": 3, "deleteFiles": 10, "push": True},
}


@dataclass
class Decision:
    kind: str  # deny or ask
    rule: str
    reason: str


def load(root: Path) -> dict | None:
    """The repo's policy, or None when it has none or the file cannot be read."""
    try:
        return json.loads((root / POLICY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_default(root: Path) -> Path:
    path = root / POLICY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT, indent=2) + "\n", encoding="utf-8")
    return path


def _segments(command: str):
    lex = shlex.shlex(command, posix=True, punctuation_chars=OPERATOR_CHARS)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    words: list[str] = []
    for token in lex:
        if token and set(token) <= set(OPERATOR_CHARS):
            if words:
                yield words
            words = []
        else:
            words.append(token)
    if words:
        yield words


def _head(words: list[str]) -> tuple[str, list[str]]:
    """The command a simple command runs, past assignments and wrappers, with the words that follow it."""
    i = 0
    while i < len(words):
        w = words[i]
        if ASSIGNMENT.match(w) or w in WRAPPERS or (w.startswith("-") and i > 0 and words[i - 1] in WRAPPERS):
            i += 1
            continue
        break
    if i >= len(words):
        return "", []
    return os.path.basename(words[i]), words[i + 1:]


def _simple_commands(command: str, depth: int = 0):
    try:
        segments = list(_segments(command))
    except ValueError:
        return
    for words in segments:
        name, rest = _head(words)
        if not name:
            continue
        yield name, rest
        if name in SHELLS and depth < 2 and "-c" in rest:
            idx = rest.index("-c")
            if idx + 1 < len(rest):
                yield from _simple_commands(rest[idx + 1], depth + 1)


def _glob(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def evaluate_path(policy: dict, root: Path, file_path: str) -> Decision | None:
    """A decision for an edit of file_path, or None when the policy allows it."""
    # The path as written, with links left alone: a link under .githooks is edited as .githooks/...
    try:
        rel = Path(os.path.abspath(file_path)).relative_to(Path(os.path.abspath(root))).as_posix()
    except ValueError:
        try:
            rel = Path(os.path.abspath(file_path)).relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
    paths = policy.get("paths", {})
    for pattern in paths.get("deny", []):
        if _glob(pattern).match(rel):
            return Decision("deny", f"paths.deny {pattern}", f"The policy in {POLICY_FILE} denies edits to {rel} (paths.deny {pattern}).")
    allow = paths.get("allow", [])
    if allow and not any(_glob(p).match(rel) for p in allow):
        return Decision("deny", "paths.allow", f"{rel} is not listed in paths.allow of {POLICY_FILE}.")
    return None


def _recent_failures(repo: str, minutes: int = 30) -> dict[str, int]:
    """Failure-log lines per gate for this repo in the last `minutes`."""
    path = Path(os.environ.get("OLIVERCODE_FAILURE_LOG") or Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode") / "failures.log")
    counts: dict[str, int] = {}
    if not path.is_file():
        return counts
    cutoff = time.time() - minutes * 60
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or parts[1] != repo:
            continue
        try:
            when = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if when >= cutoff:
            counts[parts[2]] = counts.get(parts[2], 0) + 1
    return counts


def evaluate_bash(policy: dict, command: str, repo: str = "") -> Decision | None:
    """A decision for a Bash command line: deny a command outside the policy, ask at a trigger, else None."""
    commands = policy.get("commands", {})
    allow, deny = commands.get("allow", []), commands.get("deny", [])
    triggers = policy.get("triggers", {})
    for pattern in deny:
        if re.search(pattern, command):
            return Decision("deny", f"commands.deny {pattern}", f"The policy in {POLICY_FILE} denies this command (commands.deny {pattern}).")
    ask = None
    for name, rest in _simple_commands(command):
        if allow and name not in allow:
            return Decision("deny", "commands.allow", f"`{name}` is not in commands.allow of {POLICY_FILE}. Add it there if the repo should run it.")
        sub = next((w for w in rest if not w.startswith("-")), "")
        if name == "git" and sub == "push" and triggers.get("push") and not ask:
            ask = Decision("ask", "triggers.push", "A push leaves this machine, so the policy asks the owner first.")
        limit = triggers.get("deleteFiles")
        if limit and not ask:
            targets = [w for w in rest if not w.startswith("-")]
            if (name == "rm" and len(targets) > limit) or (name == "git" and sub == "rm" and len(targets) - 1 > limit):
                ask = Decision("ask", "triggers.deleteFiles", f"This deletes more than {limit} files, so the policy asks the owner first.")
        needed = triggers.get("gateFailures")
        if needed and name == "git" and sub == "commit" and repo and not ask:
            gate, count = max(_recent_failures(repo).items(), key=lambda kv: kv[1], default=("", 0))
            if count >= needed - 1:
                ask = Decision("ask", "triggers.gateFailures", f"The {gate} gate has blocked this repo {count} times in 30 minutes, so this is attempt {count + 1}. Stop and tell the owner what keeps failing.")
    return ask


def log_block(decision: Decision, repo: str) -> None:
    """Write the decision to the failure log, in the format failure_log.record writes."""
    try:
        from lib import failure_log
        failure_log.record("policy", f"{decision.kind} {decision.rule}", repo)
        return
    except ImportError:
        pass
    try:
        base = Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode")
        path = Path(os.environ.get("OLIVERCODE_FAILURE_LOG") or base / "failures.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{when}\t{repo}\tpolicy\t{decision.kind} {decision.rule}\n")
    except OSError:
        pass
