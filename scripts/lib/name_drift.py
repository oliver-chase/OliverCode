"""`olivercode board groom` flags a command, job label or file name that differs from its README heading (#840).

A heading and an identifier belong together in two cases: the heading's section names exactly one identifier (a
`olivercode X` command, a `com.vendor.X` job label or a `path/file.ext` name in backticks), or an identifier is followed
by the heading's name in brackets, as in `olivercode showcase` (Gallery). The two names must then be the same word.
No model runs, and `drift(root)` reads only the tracked README files.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib import gitfiles

HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
COMMAND = re.compile(r"`(?:python3 )?(?:scripts/)?olivercode ([a-z][a-z0-9-]*)((?: [a-z][a-z0-9-]*)*)(?: [^`]*)?`")
LABEL = re.compile(r"`((?:com|io|org)\.[a-z0-9-]+(?:\.[a-z0-9-]+)+)`")
FILE = re.compile(r"`((?:[\w.-]+/)*[\w-]+\.(?:py|sh|json|md|plist|html))`")
ALIASED = re.compile(r"(`[^`]+`)\s*\(([A-Z][\w ]{2,40})\)")
SHOWN = 6
SUBWORDS: dict[str, list[str]] = {}  # a command's later words, so a command's second word can also answer to a name


def norm(text: str) -> str:
    """A name reduced to lowercase letters and digits, without the product name."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"olivercode", "", text.lower()))


def identifiers(text: str) -> dict[str, str]:
    """{name: kind} of every command, job label and file name the text puts in backticks, by the name a person types or finds."""
    found = {m.group(1): "command" for m in COMMAND.finditer(text)}
    SUBWORDS.update({m.group(1): m.group(2).split() for m in COMMAND.finditer(text)})
    found.update({m.group(1).rsplit(".", 1)[-1]: "job label" for m in LABEL.finditer(text)})
    for m in FILE.finditer(text):
        found.setdefault(re.sub(r"\.\w+$", "", m.group(1).rsplit("/", 1)[-1]), "file name")
    return found


def sections(text: str) -> list[tuple[str, str]]:
    """[(heading, body)] for each heading in a markdown file, outside code fences."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and (m := HEADING.match(line)):
            out.append((m.group(2).strip("` "), ""))
            continue
        if out:
            out[-1] = (out[-1][0], out[-1][1] + line + "\n")
    return out


def same(heading: str, name: str) -> bool:
    """True when one reduced name holds the other, so `Dispatch planning` and `dispatch` agree."""
    a = norm(heading)
    return not a or any(not b or a in b or b in a for b in (norm(name), *map(norm, SUBWORDS.get(name, []))))


def mismatches(text: str) -> list[str]:
    """One line per identifier that differs from the heading it belongs with, each with the fix."""
    parts = sections(text)
    headings = {norm(h): h for h, _ in parts if norm(h)}
    flags = []
    for heading, body in parts:
        names = identifiers(body)
        if len(names) == 1:
            ((name, kind),) = names.items()
            if not same(heading, name):
                flags.append((heading, kind, name))
    for m in ALIASED.finditer(text):
        for name, kind in identifiers(m.group(1)).items():
            heading = headings.get(norm(m.group(2)))
            if heading and not same(heading, name) and (heading, kind, name) not in flags:
                flags.append((heading, kind, name))
    return [f'the heading "{h}" and the {kind} `{n}` name one feature differently: use one name in both' for h, kind, n in flags]


def drift(root: Path) -> list[str]:
    """`README.md: ...` lines for every tracked README under ROOT with a heading and an identifier that differ."""
    lines = []
    for rel in gitfiles.tracked_files(Path(root), "README.md", "*/README.md"):
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        lines += [f"{rel}: {why}" for why in mismatches(text)]
    return lines


def summary(lines: list[str]) -> str:
    """The owner line for a non-empty result."""
    return f"{len(lines)} name difference(s) between a heading and an identifier: " + "; ".join(lines[:SHOWN])
