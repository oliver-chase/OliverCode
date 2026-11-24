"""Bash command-line parsing for policy.py: lexing, wrapper-unwrapping, heredoc bodies and the
views a deny pattern is matched against.

Split out of policy.py so each file reads in one sitting (#1125).
"""

from __future__ import annotations

import os
import re
import shlex

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
