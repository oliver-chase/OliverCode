#!/usr/bin/env python3
"""The audit's mechanical sweep: candidates for deletion, splitting and merging, found with no model.

Usage:
    sweep.py [repo]   # prints one `kind  file:line  detail` row per candidate
Kinds:
    unused-def   a top-level function or class in non-test code that nothing else names
    test-only    a top-level function or class that only its own tests name
    orphan       a tracked script, doc or reference that nothing else names by path or basename
    oversized    a tracked code file over 400 lines
Every row is a candidate for a reader to judge, never a verdict: a hook entry point or a CLI
handler is named by a string the sweep cannot see. It edits nothing and always exits 0.
Tests: python3 -m unittest test_sweep   (from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

from _fleet import is_test, tracked as git_tracked

CODE = {".py", ".sh", ".js", ".ts"}
TEXT = CODE | {".md", ".json", ".yml", ".yaml", ".toml", ".html", ""}
DEF = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)", re.M)
# Dunder methods, entry points and the unittest hooks are called by the runtime, never by name.
RUNTIME = {"main", "setUp", "tearDown", "setUpClass", "tearDownClass"}
LIMIT = 400


def tracked(repo):
    return [f for f in git_tracked(repo) if Path(f).suffix in TEXT]


def sweep(repo):
    files = tracked(repo)
    text = {}
    for rel in files:
        try:
            text[rel] = (Path(repo) / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            text[rel] = ""
    rows = []
    for rel in files:
        if Path(rel).suffix == ".py" and not is_test(rel):
            for m in DEF.finditer(text[rel]):
                name = m.group(1)
                if name in RUNTIME or name.startswith("__"):
                    continue
                word = re.compile(r"\b%s\b" % re.escape(name))
                users = [o for o in files if o != rel and word.search(text[o])]
                own = len(word.findall(text[rel])) > 1
                line = text[rel].count("\n", 0, m.start()) + 1
                if not users and not own:
                    rows.append(("unused-def", f"{rel}:{line}", name))
                elif users and all(is_test(o) for o in users) and not own:
                    rows.append(("test-only", f"{rel}:{line}", name))
        if rel.endswith((".py", ".sh", ".md")) and not is_test(rel):
            base = Path(rel).name
            parent = rel.startswith(("scripts/", "docs/", "core/")) or "/scripts/" in rel or "/references/" in rel
            if parent and base not in ("SKILL.md", "README.md", "CLAUDE.md", "__init__.py"):
                imported = re.compile(r"\b(?:import|from)\s+%s\b" % re.escape(Path(base).stem))
                refs = [o for o in files if o != rel and not is_test(o) and (base in text[o] or imported.search(text[o]))]
                if not refs:
                    rows.append(("orphan", rel, "nothing outside its own tests names it"))
        if Path(rel).suffix in CODE and not is_test(rel):
            n = text[rel].count("\n")
            if n > LIMIT:
                rows.append(("oversized", f"{rel}:1", f"{n} lines"))
    return rows


def main(argv):
    repo = argv[1] if len(argv) > 1 else "."
    for kind, where, detail in sweep(repo):
        print(f"{kind:11} {where}  {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
