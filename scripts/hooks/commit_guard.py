#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuses a `git commit` that would skip the repo's gates.

Git's own pre-commit hook cannot catch the case where it never runs. This hook sits one
level up, in Claude Code, and refuses a commit in four cases:

- the repo ships `.githooks/pre-commit` but git is not pointed at it (see repo_gates)
- the commit passes `--no-verify` or `-n`, which skips every hook
- the commit is wrapped in `bash -c`, `sh -c`, `zsh -c` or `eval`; the wrapped string is read as a command line
- the command overrides `core.hooksPath`: `git -c`, `--config-env` or a `GIT_CONFIG_*` variable

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
import repo_gates  # noqa: E402

# The whole command is tokenized once, so a separator inside a quoted message stays part of
# that message; splitting on the raw text first dropped any commit whose message held a
# `;`, `|` or `&&`, which is most of them.
OPERATOR_CHARS = ";&|()\n"
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "sudo", "time"}
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


def _commits(command: str, cwd: Path) -> list[tuple[Path, list[str], list[str], list[str]]]:
    """Each `git ... commit ...` in the command: (directory it runs in, config keys it sets,
    environment assignments before it, commit args). Anything unparseable yields nothing."""
    found = []
    here = cwd
    exported: list[str] = []  # `export NAME=value` reaches every later command in the line
    try:
        segments = list(_segments(command))
    except ValueError:
        return found
    for words in segments:
        env = []
        while words and (ASSIGNMENT.match(words[0]) or words[0] in WRAPPERS):
            wrapper = words[0] in WRAPPERS
            if not wrapper:
                env.append(words[0])
            words = words[1:]
            while wrapper and words and words[0].startswith("-"):
                words = words[1:]  # a wrapper's own flags, such as `env -i` or `sudo -E`
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
                found += [(w, k, exported + env + e, a) for w, k, e, a in _commits(words[flags[0] + 1], here)]
            continue
        if words and words[0] == "eval":
            found += [(w, k, exported + env + e, a) for w, k, e, a in _commits(" ".join(words[1:]), here)]
            continue
        if not words or words[0] != "git":
            continue
        keys, i, where = [], 1, here
        while i < len(words) and words[i].startswith("-"):
            w = words[i]
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if w == "-C" and nxt:
                where = (where / Path(nxt).expanduser()).resolve()
                i += 2
            elif w in ("-c", "--config-env") and nxt:
                keys.append(nxt.split("=", 1)[0].lower())
                i += 2
            elif w.startswith("-c") and len(w) > 2:
                keys.append(w[2:].split("=", 1)[0].lower())
                i += 1
            elif w.startswith("--config-env="):
                keys.append(w.split("=", 1)[1].split("=", 1)[0].lower())
                i += 1
            elif w.split("=", 1)[0] in GLOBAL_VALUE_OPTIONS and ("=" in w or nxt):
                option, value = w.split("=", 1) if "=" in w else (w, nxt)
                where = _located(where, option, value)
                i += 1 if "=" in w else 2
            else:
                i += 1
        if i < len(words) and words[i] == "commit":
            for assignment in exported + env:
                name, _, value = assignment.partition("=")
                if name in ("GIT_DIR", "GIT_WORK_TREE") and value:
                    where = _located(where, "--git-dir" if name == "GIT_DIR" else "--work-tree", value)
            found.append((where, keys, exported + env, words[i + 1:]))
    return found


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
        if a == "--no-verify":
            return True
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
