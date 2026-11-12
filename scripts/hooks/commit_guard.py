#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `git commit` that would skip the repo's gates.

Git's own pre-commit hook cannot catch the case where it never runs. This hook sits one
level up, in Claude Code, and refuses a commit in four cases:

- the repo ships `.githooks/pre-commit` but git is not pointed at it (see repo_gates)
- the commit passes `--no-verify` or `-n`, which skips every hook
- the commit is wrapped in `bash -c`, `sh -c`, `zsh -c` or `eval`; the wrapped string is read as a command line
- the command overrides `core.hooksPath`: `git -c`, `--config-env`, a `GIT_CONFIG_*` variable, or an earlier `git config` in the same line

A repo with no gates of its own commits normally, with any flags, since there is nothing to
skip; the session-start check names that gap.
Fails open on anything it cannot parse: a guard that blocks a legitimate commit because of
its own bug costs more than the rare case it misses.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import repo_gates  # noqa: E402
from lib import policy  # noqa: E402

# The whole command is tokenized once, so a separator inside a quoted message stays part of
# that message; splitting on the raw text first dropped any commit whose message held a
# `;`, `|` or `&&`, which is most of them.
OPERATOR_CHARS = ";&|()\n"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git's global options whose value is the next word; read as a subcommand, the value hid the commit.
GLOBAL_VALUE_OPTIONS = {"--git-dir", "--work-tree", "--namespace", "--super-prefix"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def _segments(command: str):
    """The simple commands in `command`, each as its list of words."""
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


def _located(where: Path, option: str, value: str) -> Path:
    """The directory a commit runs against once `--git-dir` or `--work-tree` names one."""
    path = (where / Path(value).expanduser()).resolve()
    if option == "--git-dir":
        return path.parent if path.name == ".git" else path
    return path if option == "--work-tree" else where


def _commits(command: str, cwd: Path, aliases_in: dict | None = None, depth: int = 0,
             seen: frozenset = frozenset()) -> list[tuple[Path, list[str], list[str], list[str]]]:
    """Each `git ... commit ...` in the command: (directory it runs in, config keys it sets,
    environment assignments before it, commit args). Anything unparseable yields nothing."""
    found = []
    here = cwd
    exported: list[str] = []  # `export NAME=value` reaches every later command in the line
    hooks_path_changed = False  # an earlier `git config core.hooksPath ...` reaches every later commit
    try:
        segments = list(_segments(command))
    except ValueError:
        return found
    if depth > 200:
        return found  # far past any real alias chain; loops end below by name
    for words in segments:
        # A shell function definition wraps its body: `f() { git commit -n; }; f`.
        while words and (words[0] in ("{", "}") or words[0].endswith("()")):
            words = words[1:]
        env, words = policy.unwrap(words)  # past `env`, `sudo`, `nice -n 5`, `timeout 9` and the like
        if words and words[0] == "export":
            exported += [w for w in words[1:] if ASSIGNMENT.match(w)]
            continue
        if len(words) >= 2 and words[0] == "cd":
            here = (here / Path(words[1]).expanduser()).resolve()
            continue
        if words and Path(words[0]).name in SHELLS:
            # `bash -c "git commit ..."` hides the commit inside a string; read that string as a command line.
            flags = [k for k, w in enumerate(words[1:], 1) if w.startswith("-") and not w.startswith("--") and "c" in w]
            if flags and flags[0] + 1 < len(words):
                found += [(w, k, exported + env + e, a) for w, k, e, a in _commits(words[flags[0] + 1], here, aliases_in, depth + 1, seen)]
            continue
        if words and words[0] == "eval":
            found += [(w, k, exported + env + e, a) for w, k, e, a in _commits(" ".join(words[1:]), here, aliases_in, depth + 1, seen)]
            continue
        if not words or words[0] != "git":
            continue
        keys, i, where = [], 1, here
        aliases = dict(aliases_in or {})  # `git -c alias.ci='commit -n' ci` runs a commit under another name
        while i < len(words) and words[i].startswith("-"):
            w = words[i]
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if w == "-C" and nxt:
                where = (where / Path(nxt).expanduser()).resolve()
                i += 2
            elif w in ("-c", "--config-env") and nxt:
                keys.append(nxt.split("=", 1)[0].lower())
                _alias(nxt if w == "-c" else _from_env(nxt, exported + env), aliases)
                i += 2
            elif w.startswith("-c") and len(w) > 2:
                keys.append(w[2:].split("=", 1)[0].lower())
                _alias(w[2:], aliases)
                i += 1
            elif w.startswith("--config-env="):
                keys.append(w.split("=", 1)[1].split("=", 1)[0].lower())
                _alias(_from_env(w.split("=", 1)[1], exported + env), aliases)
                i += 1
            elif w.split("=", 1)[0] in GLOBAL_VALUE_OPTIONS and ("=" in w or nxt):
                option, value = w.split("=", 1) if "=" in w else (w, nxt)
                where = _located(where, option, value)
                i += 1 if "=" in w else 2
            else:
                i += 1
        if i < len(words) and words[i] == "config":
            rest = [w.lower() for w in words[i + 1:]]
            if "core.hookspath" in rest:
                at = rest.index("core.hookspath")
                value = rest[at + 1] if at + 1 < len(rest) else ""
                unsets = any(w.startswith("--unset") for w in rest)
                # Pointing git back at the repo's own gates is the fix the refusal message recommends.
                restores = value in (".githooks", "./.githooks") and not unsets
                if (at + 1 < len(rest) or unsets) and not restores:
                    hooks_path_changed = True
        if i < len(words) and words[i].lower() in aliases:
            name = words[i].lower()
            expansion = aliases[name]
            if (name, tuple(expansion)) in seen:
                continue  # an alias that expands to itself; git refuses the loop
            args = words[i + 1:]
            rest = " ".join(shlex.quote(w) for w in args)
            if expansion[0] == "!":
                # git runs a shell alias with the remaining words appended, which its body
                # can also read as "$@" and $1..$9.
                body = expansion[1]
                for token in ('"${@}"', "${@}", '"${*}"', "${*}", '"$@"', "$@", '"$*"', "$*"):
                    body = body.replace(token, rest)
                for n in range(9, 0, -1):
                    value = shlex.quote(args[n - 1]) if n <= len(args) else ""
                    for form in (f'"${{{n}}}"', f"${{{n}}}", f'"${n}"', f"${n}"):
                        body = body.replace(form, value)
                line = f"{body} {rest}"
            else:
                # Reparse as a git command line, so a chained alias or leading global options resolve too.
                head = " ".join(shlex.quote(w) for w in words[:i] + expansion)
                line = f"{head} {rest}"
            found += [(w, k + keys, exported + env + e, a)
                      for w, k, e, a in _commits(line, where, aliases, depth + 1, seen | {(name, tuple(expansion))})]
            continue
        if i < len(words) and words[i] == "commit":
            if hooks_path_changed:
                keys = keys + ["core.hookspath"]
            for assignment in exported + env:
                name, _, value = assignment.partition("=")
                if name in ("GIT_DIR", "GIT_WORK_TREE") and value:
                    where = _located(where, "--git-dir" if name == "GIT_DIR" else "--work-tree", value)
            found.append((where, keys, exported + env, words[i + 1:]))
    return found


def _from_env(setting: str, env: list[str]) -> str:
    """`--config-env=KEY=VAR` takes its value from VAR: return KEY=value when the line sets VAR."""
    key, _, var = setting.partition("=")
    for assignment in reversed(env):
        name, _, value = assignment.partition("=")
        if name == var:
            return f"{key}={value}"
    return ""


def _alias(setting: str, aliases: dict) -> None:
    """Record `alias.NAME=commit ...` from a `git -c` setting as NAME -> its words."""
    key, _, value = setting.partition("=")
    if key.lower().startswith("alias.") and value.startswith("!"):
        aliases[key[len("alias."):].lower()] = ["!", value[1:]]  # a shell alias: read as a command line
        return
    if key.lower().startswith("alias.") and value:
        try:
            expansion = shlex.split(value)
        except ValueError:
            return
        if expansion:
            aliases[key[len("alias."):].lower()] = expansion  # git reads config keys without case


def _overrides_hooks_path(keys: list[str], env: list[str]) -> bool:
    if "core.hookspath" in keys:
        return True
    for assignment in env:
        name, _, value = assignment.partition("=")
        if name.startswith("GIT_CONFIG_KEY_") and value.lower() == "core.hookspath":
            return True
        if name == "GIT_CONFIG_PARAMETERS" and "core.hookspath" in value.lower():
            return True
    return False


VALUE_FLAGS = set("mFCct")  # commit's short flags that take a value; letters after one are that value
ATTACHED_VALUE_FLAGS = set("uS")  # optional value, only ever attached: `-uno`, `-S<keyid>`


def _skips_hooks(args: list[str]) -> bool:
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--no-v") and "--no-verify".startswith(a):
            return True  # git accepts any unambiguous prefix of a long option
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch == "n":
                    return True
                if ch in VALUE_FLAGS:
                    skip_next = k == len(a) - 2  # the value is the next word only when the flag ends the cluster
                    break
                if ch in ATTACHED_VALUE_FLAGS:
                    break
    return False


def reason(command: str, cwd: Path) -> str:
    for where, keys, env, args in _commits(command, cwd):
        root = repo_gates.repo_root(where)
        if not (root and repo_gates.has_gates(root)):
            continue
        if _skips_hooks(args):
            return "This commit passes --no-verify, which skips the repo's commit gates. Commit without it and fix what the gates report."
        if _overrides_hooks_path(keys, env):
            return "This commit overrides core.hooksPath, which disables the repo's commit gates. Commit without the override."
        problem = repo_gates.gate_problem(root)
        if problem:
            return (f"Refused: {problem}. Run `git -C \"{root}\" config core.hooksPath .githooks`, "
                    "then commit again so the gates run.")
    return ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        cwd = Path(data.get("cwd") or ".")
    except (json.JSONDecodeError, AttributeError):
        return 0
    if "commit" not in command:
        return 0
    why = reason(command, cwd)
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- fail open, never block on the hook's own bug
        raise SystemExit(0)
