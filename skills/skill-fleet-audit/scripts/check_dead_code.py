#!/usr/bin/env python3
"""DEAD-CODE-1: fails on code and files that nothing uses.

Three findings:
  - An import that no name in the file uses. A test file is skipped, since it may import for a side effect.
  - A top-level function or class whose name appears nowhere else in non-test text. A test that
    calls a helper does not keep it alive.
  - A file in a skill that no other file in the skill cites by name. The name counts with or
    without its suffix, so `import metrics` cites `metrics.py`. A file under `example/` or
    `examples/` is cited by that folder name.

An import inside `try`, an `__init__.py` and a line ending in `# noqa` are skipped. Another file
that reads the name as `module.name` keeps a re-exported import alive.

Usage:
    check_dead_code.py [ROOT]    # scan the fleet, or one folder
Exit 1 when any finding exists.
Tests: python3 -m unittest test_check_dead_code   (from this scripts/ folder)
"""
import ast
import collections
import re
import subprocess
import sys
from pathlib import Path

import _fleet

SKIP_DIRS = {"node_modules", "vendor", "__pycache__", ".git", ".pytest_cache", "worktrees"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".sh", ".js", ".jsx", ".html", ".txt", ".yml", ".yaml", ".example"}
SAMPLE_DIRS = {"example", "examples"}
WORD = re.compile(r"\w+")


def is_test(rel):
    return rel.name.startswith("test_") or "tests" in rel.parts or rel.name == "conftest.py"


def tracked(root):
    """Repo-relative paths of the files to read: tracked ones, else everything on disk."""
    res = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    names = res.stdout.splitlines() if res.returncode == 0 and res.stdout else [
        p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_file()]
    # A tracked file deleted from disk and not yet committed would fail the read.
    return [Path(n) for n in names if n and not SKIP_DIRS & set(Path(n).parts) and (Path(root) / n).is_file()]


def read_all(root):
    """{relative path: text} for every text file."""
    texts = {}
    for rel in tracked(root):
        if rel.suffix in TEXT_SUFFIXES:
            texts[rel] = (Path(root) / rel).read_text(encoding="utf-8", errors="ignore")
    return texts


def _imported_names(tree):
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            skipped.update(id(n) for stmt in node.body for n in ast.walk(stmt))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in skipped:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, (alias.asname or alias.name).split(".")[0]


def find_unused_imports(texts):
    """(path, line, name) for each import no name in its file uses."""
    parsed = {}
    for rel, text in texts.items():
        if rel.suffix == ".py" and rel.name != "__init__.py" and not is_test(rel):
            try:
                parsed[rel] = ast.parse(text)
            except SyntaxError:
                continue
    read_as_attribute = {n.attr for tree in parsed.values() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    found = []
    for rel, tree in parsed.items():
        lines = texts[rel].splitlines()
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        exported = {c.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "__all__" for t in n.targets)
                    for c in ast.walk(n.value) if isinstance(c, ast.Constant)}
        for line, name in _imported_names(tree):
            if name in used or name in exported or name in read_as_attribute or "noqa" in lines[line - 1]:
                continue
            found.append((rel, line, name))
    return sorted(found)


def find_unreferenced_defs(texts):
    """(path, line, name) for each top-level def or class that no other non-test text names."""
    counts = collections.Counter(
        w for rel, text in texts.items() if not is_test(rel) for w in WORD.findall(text))
    found = []
    for rel, text in texts.items():
        if rel.suffix != ".py" or is_test(rel):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and node.name != "main" and not node.name.startswith("__") and counts[node.name] <= 1:
                found.append((rel, node.lineno, node.name))
    return sorted(found)


def find_unreferenced_files(root, texts):
    """(skill, path) for each file in a skill that no other file in the skill cites."""
    found = []
    for folder in _fleet.find_skills(Path(root)):
        base = folder.relative_to(root)
        own = {rel.relative_to(base): text for rel, text in texts.items() if base in rel.parents}
        files = [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix != ".pyc" and p.name != ".DS_Store"
                 and not SKIP_DIRS & set(p.relative_to(folder).parts)]
        for path in files:
            rel = path.relative_to(folder)
            if rel.name == "SKILL.md" or is_test(rel):
                continue
            keys = [rel.stem] + [part for part in rel.parts[:-1] if part in SAMPLE_DIRS]
            pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(k) for k in keys) + r")(?![\w-])")
            if not any(pattern.search(text) for other, text in own.items() if other != rel):
                found.append((folder.name, rel))
    return sorted(found)


def main():
    root = _fleet.scan_root(sys.argv[1:]).resolve()
    texts = read_all(root)
    problems = [f"{p}:{n} -- import '{name}' is never used" for p, n, name in find_unused_imports(texts)]
    problems += [f"{p}:{n} -- '{name}' is defined and nothing else names it" for p, n, name in find_unreferenced_defs(texts)]
    problems += [f"{skill}/{p} -- no other file in the skill cites it" for skill, p in find_unreferenced_files(root, texts)]
    for line in problems:
        print(" -", line)
    print(f"{len(problems)} dead-code finding(s)." if problems else "No dead code found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
