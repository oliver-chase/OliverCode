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
# A wrapper runs the command that follows it. VALUE_OPTIONS lists the options that take a value, and
# OPERANDS the positional arguments (a duration) that sit between the wrapper and its command.
VALUE_OPTIONS = {"env": {"-u", "-C", "-S"}, "command": set(), "builtin": set(), "exec": {"-a"}, "nohup": set(),
                 "sudo": {"-u", "-g", "-h", "-p", "-C", "-T", "-r", "-t", "-U"}, "time": {"-f", "-o"},
                 "nice": {"-n"}, "timeout": {"-s", "-k"}, "gtimeout": {"-s", "-k"}}
OPERANDS = {"timeout": 1, "gtimeout": 1}
WRAPPERS = set(VALUE_OPTIONS)
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATOR_CHARS = ";&|()`\n"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A redirect such as 2>&1, >&2 or &>file holds `&`, which the lexer would read as an operator. A descriptor
# copy writes no file and is dropped, and &> and &>> become the file redirects > and >>.
FD_COPY = re.compile(r"\d*[<>]&(?:\d+-?|-)(?=\s|$|[;&|)])")
FD_FILE = re.compile(r"&(>>?)")
# A heredoc's body is data for the command, unless a shell reads it as its script (_shell_heredoc_bodies).
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n.*?^[ \t]*\2[ \t]*$", re.S | re.M)

DEFAULT = {
    "version": 1,
    "commands": {
        "allow": [],
        # A downloaded script piped into a shell, and a command that points git's hooks anywhere but .githooks.
        "deny": [
            r"(curl|wget)\s+.*\|\s*(ba|z)?sh",
            r"git\s+-c\s+core\.hooksPath=(?!(\./)?\.githooks\b)",
            r"git\s+config\s+(\S+\s+)*--unset(-all)?\s+core\.hooksPath",
            r"git\s+config\s+(\S+\s+)*core\.hooksPath\s+(?!(\./)?\.githooks\b)[^\s;&|]",
        ],
    },
    "paths": {
        "allow": ["**"],
        "deny": [".git/**", ".env", ".env.*", ".secrets/**", ".githooks/**", ".olivercode/**"],
    },
    "triggers": {"gateFailures": 3, "deleteFiles": 10, "push": True},
}


@dataclass
class Decision:
    kind: str  # deny or ask
    rule: str
    reason: str


def load(root: Path) -> dict | None:
    """The repo's policy, or None when it has none. A policy file that does not parse gives the default policy,
    so a broken file never lifts every rule."""
    try:
        text = (root / POLICY_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return DEFAULT


def write_default(root: Path) -> Path:
    path = root / POLICY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT, indent=2) + "\n", encoding="utf-8")
    return path


def unwrap(words: list[str]) -> tuple[list[str], list[str]]:
    """(environment assignments, the words from the command a wrapper runs). `nice -n 5 timeout 9 git x`
    gives ([], ["git", "x"]), so a guard sees the command and not the wrapper's own arguments."""
    env: list[str] = []
    while words:
        w = words[0]
        if ASSIGNMENT.match(w):
            env.append(w)
            words = words[1:]
        elif w in WRAPPERS:
            name, words = w, words[1:]
            while words and words[0].startswith("-"):
                option, words = words[0], words[1:]
                if option in VALUE_OPTIONS[name] and words:
                    words = words[1:]
            for _ in range(OPERANDS.get(name, 0)):
                words = words[1:]
        else:
            break
    return env, words


def _segments(command: str):
    command = HEREDOC.sub(lambda m: m.group(0).split("\n", 1)[0], command)
    command = FD_FILE.sub(r"\1", FD_COPY.sub("", command))
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
    _, words = unwrap(words)
    return (os.path.basename(words[0]), words[1:]) if words else ("", [])


def _shell_heredoc_bodies(command: str):
    """The body of each heredoc that a shell reads as its script, such as `bash <<EOF`."""
    for match in HEREDOC.finditer(command):
        rest = match.group(0).partition("\n")[2]
        head = command[command.rfind("\n", 0, match.start()) + 1 : match.start()]
        try:
            feeding = list(_segments(head))
        except ValueError:
            continue
        if feeding and _head(feeding[-1])[0] in SHELLS:
            yield rest.rsplit("\n", 1)[0]


def _simple_commands(command: str, depth: int = 0):
    try:
        segments = list(_segments(command))
    except ValueError:
        return
    # A heredoc is data, except when a shell reads it as its script, so that body is judged like a command.
    if depth < 2:
        for body in _shell_heredoc_bodies(command):
            yield from _simple_commands(body, depth + 1)
    for words in segments:
        name, rest = _head(words)
        if not name:
            continue
        yield name, rest
        if depth >= 2:
            continue
        if name == "eval":
            yield from _simple_commands(" ".join(rest), depth + 1)
        elif name in SHELLS:
            # -c alone or in a flag cluster such as -lc or -ic: the next word is the command string.
            idx = next((i for i, w in enumerate(rest) if w[:1] == "-" and w[1:2] != "-" and "c" in w[1:]), None)
            if idx is not None and idx + 1 < len(rest):
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


def _matches(pattern: str, rel: str) -> bool:
    """A deny pattern matches at the repo root and at any depth below it."""
    return bool(_glob(pattern).match(rel) or _glob("**/" + pattern).match(rel))


def evaluate_path(policy: dict, root: Path, file_path: str) -> Decision | None:
    """A decision for an edit of file_path, or None when the policy allows it. A relative path is read
    from the repo root, and a symlink is checked under its own name and under the file it points to."""
    base = Path(os.path.abspath(root))
    target = Path(file_path).expanduser()
    target = Path(os.path.abspath(target if target.is_absolute() else base / target))
    rels = []
    for candidate in (target, Path(os.path.realpath(target))):
        for anchor in (base, Path(os.path.realpath(base))):
            try:
                rels.append(candidate.relative_to(anchor).as_posix())
                break
            except ValueError:
                continue
    if not rels:
        return None
    paths = policy.get("paths", {})
    for rel in rels:
        for pattern in paths.get("deny", []):
            if _matches(pattern, rel):
                return Decision("deny", f"paths.deny {pattern}", f"The policy in {POLICY_FILE} denies edits to {rel} (paths.deny {pattern}).")
    allow = paths.get("allow", [])
    if allow and not any(_glob(p).match(rels[0]) for p in allow):
        return Decision("deny", "paths.allow", f"{rels[0]} is not listed in paths.allow of {POLICY_FILE}.")
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


REDIRECT = re.compile(r"^(?:\d*>>?|&>>?|>\|)$")
WRITERS_ALL = {"tee", "touch", "rm", "mv", "truncate", "chmod", "chown"}
WRITERS_LAST = {"cp", "install", "ln"}
HOME_FORMS = {"", "~", "$HOME", "${HOME}"}


def _write_targets(name: str, rest: list[str]) -> list[str]:
    """Paths a simple command writes: redirect targets, tee/touch/rm/mv targets, the destination of cp, install
    and ln, `sed -i` files and `dd of=`."""
    targets, i = [], 0
    while i < len(rest):
        w = rest[i]
        if REDIRECT.match(w) and i + 1 < len(rest):
            targets.append(rest[i + 1])
            i += 1
        elif ">" in w and len(w) > 1 and not w.endswith(">"):
            targets.append(re.split(r">+\|?", w)[-1])
        elif name == "dd" and w.startswith("of="):
            targets.append(w[3:])
        i += 1
    words = [w for w in rest if not w.startswith("-") and not REDIRECT.match(w) and not w.startswith(">")]
    if name in WRITERS_ALL or (name == "sed" and any(w.startswith("-i") or w == "--in-place" for w in rest)):
        targets += words
    elif name in WRITERS_LAST and words:
        targets.append(words[-1])
    return targets


def _recursive(rest: list[str]) -> bool:
    """An rm flag that recurses: --recursive, or r or R in a short-flag cluster."""
    return any(w == "--recursive" or (w.startswith("-") and not w.startswith("--") and ("r" in w or "R" in w)) for w in rest)


def _recursive_rm_of_home_or_root(rest: list[str]) -> bool:
    """A recursive rm whose target is `/`, `/*`, `~`, `~/` or `$HOME`, however the flags are split."""
    recursive = _recursive(rest)
    targets = [w for w in rest if not w.startswith("-") and w[:1] in "/~$"]
    return recursive and any(w.rstrip("/").removesuffix("/*").rstrip("*").rstrip("/") in HOME_FORMS for w in targets)


def _force_push(rest: list[str]) -> bool:
    """--force, -f in a flag cluster, or a refspec that starts with +, which forces that one ref."""
    flags = [w for w in rest if w.startswith("-")]
    return any(w == "--force" or (not w.startswith("--") and "f" in w[1:]) for w in flags) or any(w.startswith("+") for w in rest)


def evaluate_bash(policy: dict, command: str, repo: str = "", root: Path | None = None) -> Decision | None:
    """A decision for a Bash command line: deny a command outside the policy, a recursive delete of the
    home or root folder, a force push or a write to a denied path, ask at a trigger, else None."""
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
        sub = _subcommand(name, rest)
        if name == "rm" and _recursive_rm_of_home_or_root(rest):
            return Decision("deny", "rm home or root", "A recursive delete of the root or home folder is always denied.")
        if name == "git" and sub == "push" and _force_push(rest):
            return Decision("deny", "git push --force", "A force push rewrites shared history, so the policy denies it. Use --force-with-lease and ask the owner.")
        if root is not None:
            for target in _write_targets(name, rest):
                hit = evaluate_path(policy, root, target)
                if hit and hit.kind == "deny":
                    return Decision("deny", hit.rule, hit.reason.replace("denies edits to", "denies writes from Bash to"))
        if name == "git" and sub == "push" and triggers.get("push") and not ask:
            ask = Decision("ask", "triggers.push", "A push leaves this machine, so the policy asks the owner first.")
        limit = triggers.get("deleteFiles")
        if limit and not ask:
            targets = [w for w in rest if not w.startswith("-")]
            if (name == "rm" and (_recursive(rest) or len(targets) > limit)) or (name == "git" and sub == "rm" and len(targets) - 1 > limit):
                ask = Decision("ask", "triggers.deleteFiles", "This deletes a folder or more than " + str(limit) + " files, so the policy asks the owner first.")
        needed = triggers.get("gateFailures")
        if needed and name == "git" and sub == "commit" and repo and not ask:
            gate, count = max(_recent_failures(repo).items(), key=lambda kv: kv[1], default=("", 0))
            if count >= needed - 1:
                ask = Decision("ask", "triggers.gateFailures", f"The {gate} gate has blocked this repo {count} times in 30 minutes, so this is attempt {count + 1}. Stop and tell the owner what keeps failing.")
    return ask


def _subcommand(name: str, rest: list[str]) -> str:
    """The first word after the command that is not a flag, skipping the values of git's -C and -c."""
    skip = False
    for w in rest:
        if skip:
            skip = False
        elif name == "git" and w in ("-C", "-c"):
            skip = True
        elif not w.startswith("-"):
            return w
    return ""


def log_block(decision: Decision, repo: str) -> None:
    """Write the decision to the failure log, in the format failure_log.record writes."""
    from lib import failure_log
    failure_log.record("policy", f"{decision.kind} {decision.rule}", repo)
