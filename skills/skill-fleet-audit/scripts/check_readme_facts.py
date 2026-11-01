#!/usr/bin/env python3
"""README-FACTS-1: fails when the root README names a family, dependency or path that disagrees with the files.

The README is the one place that describes the fleet, so a wrong claim there misleads every reader.
`check_doc_sync.py` already checks that each skill has a table row. This check reads the claims
around those rows:
  1. When the README has a code-block tree, its top-level entries are exactly the folders directly
     under the fleet root (hidden folders and `docs/` aside).
  2. Each row of the "Dependency model" table names the dependencies the files declare: the
     `_REQUIRES` lines in that folder.
  3. Each backticked file name, or folder ending in `/`, outside code blocks exists on disk.
A name that is a placeholder, a command, a person's own file or a path under `~` is skipped. So is
`CLAUDE.md`, which the README names as a file in other repositories.

Usage:
    check_readme_facts.py [ROOT]    # check ROOT/README.md, default the fleet root
Exit 1 when a claim disagrees with the files.
Tests: python3 -m unittest test_check_readme_facts   (from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

from _fleet import scan_root

FILE_EXT = (".md", ".py", ".js", ".json", ".sh", ".css")
EXTERNAL_FILES = {"CLAUDE.md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", ".pytest_cache", ".claude"}
TREE_LINE = re.compile(r"^[├└]── ([a-z0-9-]+)/\s*$")  # top level only: a nested entry starts with `│` or spaces
CODE_SPAN = re.compile(r"`([^`\n]+)`")
DEP_ROW = re.compile(r"^\|\s*`([a-z0-9/-]+)`\s*\|\s*([^|]*?)\s*\|")


def all_paths(root):
    """Every file and folder path under root, as posix strings relative to root."""
    found = set()
    for path in Path(root).rglob("*"):
        rel = path.relative_to(root)
        if set(rel.parts) & SKIP_DIRS:
            continue
        found.add(rel.as_posix() + ("/" if path.is_dir() else ""))
    return found


def exists(token, paths):
    """True when some path equals the token or ends with it after a slash."""
    return any(p == token or p.endswith("/" + token) for p in paths)


def readme_lines(root):
    text = (Path(root) / "README.md").read_text(encoding="utf-8")
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        yield line, in_code


def readme_tree(root):
    """The top-level folder names the README's code-block trees list, or None when it has no tree."""
    names = []
    for line, in_code in readme_lines(root):
        if in_code:
            m = TREE_LINE.match(line.rstrip())
            if m:
                names.append(m.group(1))
    return names or None


def declared_dependencies(root, folder):
    """What the files declare for one folder: its `_REQUIRES` lines."""
    requires = Path(root) / folder / "_REQUIRES"
    if not requires.is_file():
        return set()
    return {line.strip() for line in requires.read_text(encoding="utf-8").splitlines() if line.strip()}


def dependency_rows(root):
    """(folder, readme dependencies) per row of the Dependency model table."""
    rows, in_section = [], False
    for line, in_code in readme_lines(root):
        if in_code:
            continue
        if line.startswith("## "):
            in_section = line.strip() == "## Dependency model"
        if in_section:
            m = DEP_ROW.match(line.strip())
            if m:
                rows.append((m.group(1), set(re.findall(r"`([a-z0-9-]+)`", m.group(2)))))
    return rows


def skippable(token):
    return (token in EXTERNAL_FILES or " " in token or token.startswith((".", "~", "$", "<")) or "<" in token or "*" in token
            or "://" in token or token.endswith((".xlsx", ".local")))


def path_tokens(root):
    for line, in_code in readme_lines(root):
        if in_code:
            continue
        for token in CODE_SPAN.findall(line):
            if skippable(token):
                continue
            if token.endswith(FILE_EXT) or (token.endswith("/") and token != "/"):
                yield token


def check(root):
    problems = []
    folders = {p.name for p in Path(root).iterdir()
               if p.is_dir() and p.name not in SKIP_DIRS and p.name != "docs" and not p.name.startswith(".")}
    listed = readme_tree(root)
    if listed is not None:
        for name in sorted(folders - set(listed)):
            problems.append(f"{name}/ is on disk, not in the README tree")
        for name in sorted(set(listed) - folders):
            problems.append(f"the README tree lists {name}/, which is not on disk")
    for folder, claimed in dependency_rows(root):
        if not (Path(root) / folder).is_dir():
            problems.append(f"Dependency model row {folder} has no folder")
            continue
        declared = declared_dependencies(root, folder)
        if claimed != declared:
            problems.append(f"{folder}: README says {sorted(claimed) or 'none'}, files declare {sorted(declared) or 'none'}")
    paths = all_paths(root)
    for token in sorted(set(path_tokens(root))):
        if not exists(token, paths):
            problems.append(f"README names `{token}`, which is not on disk")
    return problems


def main(argv):
    root = scan_root(argv)
    if not (Path(root) / "README.md").is_file():
        print(f"No README.md in {root} -- README facts skipped.")
        return 0
    problems = check(root)
    for p in problems:
        print(f"  {p}")
    if problems:
        print(f"README facts: {len(problems)} claim(s) disagree with the files.")
        return 1
    print("README facts clean: the tree, the dependency table and every named path match the files.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
