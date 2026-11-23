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
import subprocess
import time
from collections import Counter
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
    # Installs the owner has forbidden: [{"manager": "pip|brew|npm|...|*", "package": "glob", "reason": "..."}].
    "installs": {"deny": []},
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
    return lex(FD_FILE.sub(r"\1", FD_COPY.sub("", command)))


def lex(command: str):
    """The simple commands in `command`, each as its list of words. A quoted separator stays in its word."""
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


def lex_uncommented(command: str):
    """`lex` after dropping each unquoted `# comment` to the line end, so only command words remain."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, "#"
    return lex("".join(f" {shlex.quote(t)}" if t.strip(OPERATOR_CHARS) else f" {t}" for t in lexer))


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
    for _env, name, rest in _commands_with_env(command, depth):
        yield name, rest


def _commands_with_env(command: str, depth: int = 0):
    """(environment assignments, command name, words after it) for each simple command, nested shell bodies included."""
    try:
        segments = list(_segments(command))
    except ValueError:
        return
    # A heredoc is data, except when a shell reads it as its script, so that body is judged like a command.
    if depth < 2:
        for body in _shell_heredoc_bodies(command):
            yield from _commands_with_env(body, depth + 1)
    for words in segments:
        env, unwrapped = unwrap(words)
        if not unwrapped:
            continue
        name, rest = os.path.basename(unwrapped[0]), unwrapped[1:]
        yield env, name, rest
        if depth >= 2:
            continue
        if name == "eval":
            yield from _commands_with_env(" ".join(rest), depth + 1)
        elif name in SHELLS:
            # -c alone or in a flag cluster such as -lc or -ic: the next word is the command string.
            idx = next((i for i, w in enumerate(rest) if w[:1] == "-" and w[1:2] != "-" and "c" in w[1:]), None)
            if idx is not None and idx + 1 < len(rest):
                yield from _commands_with_env(rest[idx + 1], depth + 1)


def _view(command: str) -> str:
    """The command line as its parsed words, operators kept. A quoted word that holds a space or an operator has them
    replaced by a placeholder, so text inside a commit message or an echo cannot match a pattern that reads the structure
    of the line, while an option such as `-c "core.hooksPath=x"` reads the same quoted or not."""
    command = HEREDOC.sub(lambda m: m.group(0).split("\n", 1)[0], command)
    command = FD_FILE.sub(r"\1", FD_COPY.sub("", command))
    lexer = shlex.shlex(command, posix=True, punctuation_chars=OPERATOR_CHARS)
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, ""
    out = []
    for token in lexer:
        operator = bool(token) and set(token) <= set(OPERATOR_CHARS)
        out.append(token if operator else re.sub(rf"[\s{re.escape(OPERATOR_CHARS)}]", "\x00", token))
    return " ".join(out)


def _pattern_views(command: str, depth: int = 0) -> list[str]:
    """The line a deny pattern is matched against, then the command string of each `bash -c` and `eval` in it. A line
    that does not parse is matched as written."""
    try:
        views = [_view(command)]
        if depth < 2:
            for words in _segments(command):
                name, rest = _head(words)
                if name == "eval":
                    views += _pattern_views(" ".join(rest), depth + 1)
                elif name in SHELLS:
                    idx = next((i for i, w in enumerate(rest) if w[:1] == "-" and w[1:2] != "-" and "c" in w[1:]), None)
                    if idx is not None and idx + 1 < len(rest):
                        views += _pattern_views(rest[idx + 1], depth + 1)
            for body in _shell_heredoc_bodies(command):
                views += _pattern_views(body, depth + 1)
        return views
    except ValueError:
        return [command]


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
                return Decision("deny", f"paths.deny {pattern}", f"The policy in {POLICY_FILE} denies edits to {rel} (paths.deny {pattern}). See docs/RULES.md, Execution.")
    allow = paths.get("allow", [])
    if allow and not any(_glob(p).match(rels[0]) for p in allow):
        return Decision("deny", "paths.allow", f"{rels[0]} is not listed in paths.allow of {POLICY_FILE}. See docs/RULES.md, Execution.")
    return None


# The pre-tool guards and the maintenance run log their own refusals under these names. Only a commit gate that blocked
# a commit counts toward triggers.gateFailures, so an unrelated denial never makes the third commit ask.
NON_COMMIT_GATES = {"policy", "commit_guard", "archived_guard", "placement_guard", "reset_guard", "main_checkout_guard", "model_guard",
                    "gh_guard", "memory_guard", "maintain", "pre-push"}


def _recent_failures(repo: str, minutes: int = 30) -> dict[str, int]:
    """Commit-gate failure-log lines per gate for this repo in the last `minutes`."""
    from lib import failure_log
    cutoff = datetime.fromtimestamp(time.time() - minutes * 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dict(Counter(gate for when, where, gate, _ in failure_log.entries() if where == repo and when >= cutoff and gate not in NON_COMMIT_GATES))


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
        elif ">" in w and len(w) > 1 and not w.endswith(">") and not re.search(r"\s", w):  # a word holding a space is quoted text
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


def _skips_hooks(rest: list[str]) -> bool:
    """--no-verify, or --no-verify=..., among the push flags (a refspec never starts with a dash)."""
    return any(w == "--no-verify" or w.startswith("--no-verify=") for w in rest)


def _branch_override(env: list[str]) -> bool:
    """ALLOW_BRANCH_PUSH=1 set in the environment of this one git command, as a prefix or through `env`. The text inside an
    echo or a commit message, and the prefix of another command in the line, does not lift the branch gate."""
    return "ALLOW_BRANCH_PUSH=1" in env


def _current_branch(repo: str, rest: list[str]) -> str:
    """The branch checked out where the push runs, honouring `git -C dir`; empty on a detached head or outside a repo."""
    where = repo or "."
    before = rest[:rest.index("push")] if "push" in rest else []
    if "-C" in before and before.index("-C") + 1 < len(before):
        where = os.path.join(where, before[before.index("-C") + 1])
    done = subprocess.run(["git", "-C", where, "symbolic-ref", "--quiet", "--short", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip()


def _pushed_branches(rest: list[str], repo: str = "") -> list[str]:
    """The branch names a `git push` creates or updates on the remote: the destination of each refspec, so
    `local:refs/heads/x` names x. A push with no refspec, such as a bare `git push`, updates the checked-out branch.
    A delete (`--delete`, `-d` or `:x`) and a tag push name none."""
    whole, rest = rest, rest[rest.index("push") + 1:] if "push" in rest else rest
    if any(w in ("--delete", "-d", "--tags") for w in rest):
        return []
    positional = [w for w in rest if not w.startswith("-")]
    if len(positional) < 2:
        current = _current_branch(repo, whole)
        return [current] if current else []
    names = []
    for spec in positional[1:]:
        dest = spec.lstrip("+").rpartition(":")[2] if ":" in spec else spec.lstrip("+")
        if spec.lstrip("+").startswith(":") or dest.startswith("refs/tags/") or dest == "HEAD":
            continue
        names.append(dest.removeprefix("refs/heads/"))
    return names


def _other_remote(rest: list[str]) -> bool:
    """True when a `git push` names a remote besides origin or rewrites history with a lease. A bare push and a push to origin go to the repo's own remote."""
    rest = rest[rest.index("push") + 1:] if "push" in rest else rest
    if any(w.startswith("--force-with-lease") for w in rest):
        return True
    words = [w for w in rest if not w.startswith("-")]
    return bool(words) and words[0] != "origin"


def _default_branch(repo: str) -> str:
    done = subprocess.run(["git", "-C", repo or ".", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], capture_output=True, text=True)
    return done.stdout.strip().removeprefix("origin/") or "main"


BRANCH_PUSH_MESSAGE = ("{branch} is not the default branch. Decide now without asking the owner: fix it and land it on {default}, discard it, or save it with `olivercode wip`. "
                       "ALLOW_BRANCH_PUSH=1 overrides one command. See docs/RULES.md, Execution.")


INSTALL_SUBCOMMANDS = {"pip": {"install"}, "pipx": {"install", "inject"}, "brew": {"install", "reinstall", "upgrade"},
                       "npm": {"install", "i", "add"}, "pnpm": {"install", "i", "add"}, "yarn": {"add", "install"},
                       "uv": {"add", "install"}, "gem": {"install"}, "cargo": {"install"}, "go": {"install"}}
PACKAGE_NAME = re.compile(r"^(?:@[\w.-]+/)?[\w.+-]+")


def _installed_packages(name: str, rest: list[str]) -> tuple[str, list[str]]:
    """(manager, packages) for a package-manager install such as `pip install x==1`, `python -m pip install x`
    or `uv pip install x`, and ("", []) for any other command. A version, extra or git ref is cut from the name."""
    manager = {"pip3": "pip", "python": "pip", "python3": "pip"}.get(name, name)
    if name in ("python", "python3"):
        if rest[:2] != ["-m", "pip"]:
            return "", []
        rest = rest[2:]
    elif name == "uv" and rest[:1] == ["pip"]:
        rest, manager = rest[1:], "pip"
    if manager not in INSTALL_SUBCOMMANDS:
        return "", []
    sub = _subcommand(manager, rest)
    if sub not in INSTALL_SUBCOMMANDS[manager]:
        return "", []
    packages = []
    for w in rest[rest.index(sub) + 1:]:
        match = PACKAGE_NAME.match(w) if not w.startswith("-") else None
        if match:
            packages.append(match.group(0).lower())
    return manager, packages


def _forbidden_install(policy: dict, name: str, rest: list[str]) -> Decision | None:
    rules = policy.get("installs", {}).get("deny", [])
    if not rules:
        return None
    manager, packages = _installed_packages(name, rest)
    for rule in rules:
        if rule.get("manager", "*") not in ("*", manager):
            continue
        for package in packages:
            if fnmatch.fnmatchcase(package, str(rule.get("package", "")).lower()):
                why = rule.get("reason") or "the owner has forbidden it"
                return Decision("deny", f"installs.deny {rule.get('package')}", f"The policy in {POLICY_FILE} denies installing {package} with {manager}: {why} (installs.deny {rule.get('package')}).")
    return None


def evaluate_bash(policy: dict, command: str, repo: str = "", root: Path | None = None) -> Decision | None:
    """A decision for a Bash command line: deny a command outside the policy, a recursive delete of the
    home or root folder, a force push or a write to a denied path, ask at a trigger, else None."""
    commands = policy.get("commands", {})
    allow, deny = commands.get("allow", []), commands.get("deny", [])
    triggers = policy.get("triggers", {})
    views = _pattern_views(command)
    for pattern in deny:
        if any(re.search(pattern, view) for view in views):
            return Decision("deny", f"commands.deny {pattern}", f"The policy in {POLICY_FILE} denies this command (commands.deny {pattern}). See docs/RULES.md, Execution.")
    ask = None
    for env, name, rest in _commands_with_env(command):
        if allow and name not in allow:
            return Decision("deny", "commands.allow", f"`{name}` is not in commands.allow of {POLICY_FILE}. Add it there if the repo should run it. See docs/RULES.md, Execution.")
        sub = _subcommand(name, rest)
        hit = _forbidden_install(policy, name, rest)
        if hit:
            return hit
        if name == "rm" and _recursive_rm_of_home_or_root(rest):
            return Decision("deny", "rm home or root", "A recursive delete of the root or home folder is always denied. See docs/RULES.md, Execution.")
        if name == "git" and sub == "push" and _force_push(rest):
            return Decision("deny", "git push --force", "A force push rewrites shared history, so the policy denies it. Use --force-with-lease and ask the owner. See docs/RULES.md, Execution.")
        if name == "git" and sub == "push" and _skips_hooks(rest):
            return Decision("deny", "git push --no-verify", "`git push --no-verify` skips every pre-push gate, so the policy refuses it. Run the push without the flag and fix what the gates report. See docs/GATES.md, Pre-push gates.")
        if name == "git" and sub == "push" and not _branch_override(env):
            default = _default_branch(repo)
            stray = [b for b in _pushed_branches(rest, repo) if b not in (default, "main", "master")]
            if stray:
                return Decision("deny", "git push branch", BRANCH_PUSH_MESSAGE.format(branch=stray[0], default=default))
        if root is not None:
            for target in _write_targets(name, rest):
                hit = evaluate_path(policy, root, target)
                if hit and hit.kind == "deny":
                    return Decision("deny", hit.rule, hit.reason.replace("denies edits to", "denies writes from Bash to"))
        if name == "git" and sub == "push" and triggers.get("push") and not ask and _other_remote(rest):
            ask = Decision("ask", "triggers.push", "This push goes to a remote besides origin, so the policy asks first. A push to origin passes, because the pre-push gates validate it. See docs/GATES.md, Pre-push gates.")
        limit = triggers.get("deleteFiles")
        if limit and not ask:
            targets = [w for w in rest if not w.startswith("-")]
            if (name == "rm" and (_recursive(rest) or len(targets) > limit)) or (name == "git" and sub == "rm" and len(targets) - 1 > limit):
                ask = Decision("ask", "triggers.deleteFiles", "This deletes a folder or more than " + str(limit) + " files, so the policy asks first. See docs/RULES.md, Execution.")
        needed = triggers.get("gateFailures")
        if needed and name == "git" and sub == "commit" and repo and not ask:
            gate, count = max(_recent_failures(repo).items(), key=lambda kv: kv[1], default=("", 0))
            if count >= needed - 1:
                ask = Decision("ask", "triggers.gateFailures", f"The {gate} gate has blocked this repo {count} times in 30 minutes, so this is attempt {count + 1}. Run the diagnosing-bugs loop on the cause. See docs/RULES.md, Execution.")
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
