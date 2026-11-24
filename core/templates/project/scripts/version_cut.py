#!/usr/bin/env python3
"""The daily version cut. Managed file: `olivercode bootstrap` keeps it level with OliverCode's copy.

Reads every commit on main since the previous cut, picks MAJOR, MINOR or PATCH from the rules in
docs/VERSIONING.md, sets VERSION and writes that version's CHANGELOG.md section grouped by story.
No commit since the previous cut makes no new version. --story is required.

    python3 scripts/version_cut.py --story REF [--day YYYY-MM-DD] [--ref main] [--commit]

Standard library only. No ordinary commit edits VERSION or CHANGELOG.md; the cut sets OLIVERCODE_VERSION_CUT=1
for its own commit, which the version-files commit gate lets through.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

LEVELS = ("PATCH", "MINOR", "MAJOR")
FIRST = (1, 0, 0)
CUT_SUBJECT = "Cut version"
STORY = re.compile(r"\(#(\d+)[^)]*\)\s*$")
STORY_LINE = re.compile(r"^Story:\s*#?(\d+)\s*$", re.M)
HEADER = re.compile(r"^## (\d+)\.(\d+)\.(\d+) - (\d{4}-\d{2}-\d{2})\s*$", re.M)
FENCE = re.compile(r"```cut-rules\n(.*?)```", re.S)
TITLE = "# Changelog\n\nEach section is one day of activity, cut by `olivercode version-cut` from the rules in `docs/VERSIONING.md`.\n"


def git(root: Path, *args: str, env: dict | None = None) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def load_rules(root: Path) -> dict:
    text = (root / "docs" / "VERSIONING.md").read_text(encoding="utf-8")
    block = FENCE.search(text)
    if not block:
        raise ValueError("docs/VERSIONING.md has no cut-rules block")
    rules = json.loads(block.group(1))
    for level in ("major", "minor"):
        rules.setdefault(level, {}).setdefault("words", [])
        rules[level].setdefault("paths", [])
    return rules


def commits_since_cut(root: Path, ref: str = "main") -> list[dict]:
    """Each non-merge commit on ref since the previous cut commit (all of them before the first cut), oldest first, with its changed files."""
    sep, end = "\x1f", "\x1e"
    last = git(root, "log", ref, "-1", "--format=%H", f"--grep=^{CUT_SUBJECT}").strip()
    out = git(root, "log", f"{last}..{ref}" if last else ref, "--no-merges", "--reverse", "--name-status", "-M",
              f"--format={end}%H{sep}%cI{sep}%s{sep}%b{sep}")
    commits = []
    for chunk in out.split(end)[1:]:
        sha, _, subject, body, files = chunk.split(sep, 4)
        if subject.startswith(CUT_SUBJECT):
            continue
        changed = []
        for line in files.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changed.append((parts[0][0], parts[1], parts[-1]))  # status, old path, new path
        commits.append({"sha": sha, "subject": subject.strip(), "body": body.strip(), "files": changed})
    return commits


def story_of(commit: dict) -> str:
    """The story a commit files under: the (#N) at the end of its subject, else a `Story: #N` line in its body."""
    match = STORY.search(commit["subject"]) or STORY_LINE.search(commit["body"])
    return f"#{match.group(1)}" if match else ""


def _words(subject: str, words: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", subject, re.I) for w in words)


def _match(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def level_of(commit: dict, rules: dict) -> str:
    major, minor = rules["major"], rules["minor"]
    gone = [old for status, old, _ in commit["files"] if status in "DR"]
    added = [new for status, _, new in commit["files"] if status == "A"]
    if any(_match(p, major["paths"]) for p in gone):
        return "MAJOR"
    if _words(commit["subject"], minor["words"]) or any(_match(p, minor["paths"]) for p in added):
        return "MINOR"
    return "PATCH"


def pick_level(commits: list[dict], rules: dict) -> tuple[str, list[dict]]:
    """The highest level any commit reaches, and the commits that reach MAJOR."""
    levels = [(level_of(c, rules), c) for c in commits]
    top = max((l for l, _ in levels), key=LEVELS.index, default="PATCH")
    return top, [c for l, c in levels if l == "MAJOR"]


def bump(current: tuple[int, int, int] | None, level: str) -> tuple[int, int, int]:
    """The next version. Each number is an integer that only counts up, so 1.9.0 is followed by 1.10.0."""
    if current is None:
        return FIRST
    major, minor, patch = current
    if level == "MAJOR":
        return (major + 1, 0, 0)
    if level == "MINOR":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def read_version(root: Path) -> tuple[int, int, int] | None:
    path = root / "VERSION"
    if not path.is_file():
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", path.read_text(encoding="utf-8").strip())
    if not match:
        raise ValueError("VERSION does not hold MAJOR.MINOR.PATCH")
    return tuple(int(n) for n in match.groups())  # type: ignore[return-value]


def upgrade_note(commit: dict) -> str:
    for line in commit["body"].splitlines():
        if line.strip().lower().startswith("upgrade:"):
            return line.strip()[len("upgrade:"):].strip()
    return f"{commit['subject']}. Read this commit's change before updating a fleet repo that relied on what it removed or renamed."


def section(version: tuple[int, int, int], day: str, level: str, commits: list[dict], majors: list[dict]) -> str:
    name = ".".join(map(str, version))
    lines = [f"## {name} - {day}", ""]
    if level == "MAJOR":
        lines += [f"Breaking: {len(majors)} change{'s' if len(majors) != 1 else ''} removed or renamed something a user or fleet repo relies on.", ""]
    groups: dict[str, list[dict]] = {}
    for c in commits:
        groups.setdefault(story_of(c) or "No story", []).append(c)
    for story, items in sorted(groups.items(), key=lambda kv: (kv[0] == "No story", int(kv[0][1:]) if kv[0] != "No story" else 0)):
        lines.append(f"### {story}")
        lines += [f"- {STORY.sub('', c['subject']).strip()} ({c['sha'][:7]})" for c in items]
        lines.append("")
    if level == "MAJOR":
        lines += ["### Upgrade notes"]
        lines += [f"- {story_of(c) or c['sha'][:7]}: {upgrade_note(c)}" for c in majors]
        lines.append("")
    return "\n".join(lines)


def cut(root: Path, day: str, ref: str = "main", out=print) -> tuple[str, tuple[int, int, int] | None]:
    """Run one cut. Returns what happened ("cut" or "empty") and the new version when one was cut."""
    commits = commits_since_cut(root, ref)
    if not commits:
        out(f"No commit reached {ref} since the previous cut, so no new version is cut.")
        return "empty", None
    level, majors = pick_level(commits, load_rules(root))
    current = read_version(root)
    new = bump(current, level)
    (root / "VERSION").write_text(".".join(map(str, new)) + "\n", encoding="utf-8")
    log = root / "CHANGELOG.md"
    old = log.read_text(encoding="utf-8") if log.is_file() else TITLE
    head, _, rest = old.partition("\n## ")
    body = section(new, day, level if current else "FIRST", commits, majors)
    log.write_text(head.rstrip("\n") + "\n\n" + body + ("\n## " + rest if rest else ""), encoding="utf-8")
    out(f"Cut {'.'.join(map(str, new))} for {day}: {level if current else 'first cut'}, {len(commits)} commit(s).")
    return "cut", new


def commit_cut(root: Path, version: tuple[int, int, int], story: str) -> None:
    ref = story if story.startswith("#") else f"#{story}"
    git(root, "add", "VERSION", "CHANGELOG.md")
    git(root, "commit", "-m", f"{CUT_SUBJECT} {'.'.join(map(str, version))} ({ref})\n\nNo test: the cut's output is generated.", "--", "VERSION", "CHANGELOG.md",
        env={**os.environ, "OLIVERCODE_VERSION_CUT": "1"})


def main(argv: list[str]) -> int:
    opts = {"--day": date.today().isoformat(), "--ref": "main", "--story": ""}
    flags = set()
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg in opts and rest:
            opts[arg] = rest.pop(0)
        elif arg == "--commit":
            flags.add(arg)
        else:
            print("Usage: version_cut.py --story REF [--day YYYY-MM-DD] [--ref main] [--commit]")
            return 1
    if not opts["--story"]:
        print("version_cut.py: pass --story REF, the story this cut is filed under.")
        return 1
    root = Path(__file__).resolve().parent.parent
    state, version = cut(root, opts["--day"], opts["--ref"])
    if version and "--commit" in flags:
        commit_cut(root, version, opts["--story"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
