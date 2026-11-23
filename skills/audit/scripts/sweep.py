#!/usr/bin/env python3
"""The audit's mechanical sweep: candidates for deletion, splitting and merging, found with no model.

Usage:
    sweep.py [repo]   # prints one `kind  file:line  detail` row per candidate
Kinds:
    unused-def   a top-level function or class in non-test code that nothing else names
    test-only    a top-level function or class that only its own tests name
    orphan       a tracked script, doc or reference under scripts/, docs/, core/ or a skill's scripts/ and references/ that nothing else names by path or basename
    oversized    a tracked code file over 400 lines
Every row is a candidate for a reader to judge: a hook entry point or a CLI
handler is named by a string the sweep cannot see. It edits nothing and exits 0 on a finished run.
Tests: python3 -m unittest test_sweep   (from this scripts/ folder)
"""

import collections
import re
import sys
from pathlib import Path

from _fleet import is_test, read, tracked as git_tracked

CODE = {".py", ".sh", ".js", ".ts"}
TEXT = CODE | {".md", ".json", ".yml", ".yaml", ".toml", ".html", ""}
WORD = re.compile(r"\w+")
DEF = re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)
# Module-level dunders, entry points and the unittest hooks are called by the runtime, never by name. Only top-level defs are scanned.
RUNTIME = {"main", "setUp", "tearDown", "setUpClass", "tearDownClass"}
LIMIT = 400


def tracked(repo):
    return [f for f in git_tracked(repo) if Path(f).suffix in TEXT]


def sweep(repo):
    files = tracked(repo)
    text = {rel: read(repo, rel) for rel in files}
    words = {rel: collections.Counter(WORD.findall(body)) for rel, body in text.items()}
    rows = []
    for rel in files:
        if Path(rel).suffix == ".py" and not is_test(rel):
            for m in DEF.finditer(text[rel]):
                name = m.group(1)
                if name in RUNTIME or name.startswith("__"):
                    continue
                users = [o for o in files if o != rel and Path(o).suffix in CODE | {""} and name in words[o]]
                own = words[rel][name] > 1
                line = text[rel].count("\n", 0, m.start()) + 1
                if not users and not own:
                    rows.append(("unused-def", f"{rel}:{line}", name))
                elif users and all(is_test(o) for o in users) and not own:
                    rows.append(("test-only", f"{rel}:{line}", name))
        if rel.endswith((".py", ".sh", ".md")) and not is_test(rel):
            base = Path(rel).name
            parent = rel.startswith(("scripts/", "docs/", "core/")) or "/scripts/" in rel or "/references/" in rel
            if parent and base not in ("SKILL.md", "README.md", "CLAUDE.md", "__init__.py"):
                named = re.compile(r"(?<![\w.-])%s(?!\w)" % re.escape(base))
                stem = re.escape(Path(base).stem)
                imported = re.compile(r"^[ \t]*(?:(?:import|from)[ \t]+(?:[\w.]+\.)?%s\b|from[ \t]+[\w.]+[ \t]+import[ \t]+[^\n]*\b%s\b)" % (stem, stem), re.M)
                refs = [o for o in files if o != rel and not is_test(o) and Path(base).stem in text[o]
                        and (named.search(text[o]) or (Path(o).suffix in (".py", ".sh", "") and imported.search(text[o])))]
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
        shown = '"' + where + '"' if any(c.isspace() for c in where) else where
        print(f"{kind:11} {shown}  {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
