"""The weight pass and the route report of check_skill_structure.py (SKILL-WEIGHT-1).

`--weight` prints one ranked table of every skill with the counts that suggest excess and `--routes` lists route rows
that load more than 2,000 words. Neither makes a judgment. check_skill_structure.py re-exports these names.
"""

import re

import _fleet

# SKILL-WEIGHT-1: files that exist for the tooling and serve no step in the skill.
WEIGHT_EXEMPT_NAMES = {"SKILL.md", "README.md", "DECISIONS.md"}
WEIGHT_SKIP_DIRS = {"__pycache__", "node_modules", ".git", "dist"}
SCRIPT_SUFFIXES = {".py", ".js", ".sh"}


def skill_files(skill_dir):
    return [p for p in sorted(skill_dir.rglob("*"))
            if p.is_file() and not (WEIGHT_SKIP_DIRS & set(p.relative_to(skill_dir).parts))
            and p.suffix != ".pyc"]


def weight_row(skill_dir):
    """Counts for one skill from its real files. No judgment, no threshold."""
    files = skill_files(skill_dir)
    texts = {}
    for f in files:
        if f.suffix in {".md", ".json", ".py", ".js", ".sh", ".txt", ""}:
            texts[f] = f.read_text(encoding="utf-8", errors="ignore")

    def named_elsewhere(target):
        # A script is named by its module stem when another file imports it. A file in a folder
        # that the router loads by pattern, such as `modes/<mode>.md`, is named by the folder.
        needles = [target.stem if target.suffix in {".py", ".js", ".jsx"} else target.name]
        if target.parent != skill_dir:
            needles.append(f"{target.parent.name}/<")
        return any(n in text for other, text in texts.items() if other != target for n in needles)

    unref, uncalled, unloaded = [], [], []
    for f in files:
        rel = f.relative_to(skill_dir)
        if f.name in WEIGHT_EXEMPT_NAMES or f.name.startswith("test_") or f.name.startswith("."):
            continue
        if named_elsewhere(f):
            continue
        unref.append(str(rel))
        if rel.parts[0] == "scripts" and f.suffix in SCRIPT_SUFFIXES:
            uncalled.append(str(rel))
        if rel.parts[0] == "references" and f.suffix == ".md":
            unloaded.append(str(rel))
    tests_dir = skill_dir.parent / "tests" / skill_dir.name
    # An import line alone proves only that the module loads, so import lines do not count.
    test_lines = [line for f in [*(tests_dir.rglob("*") if tests_dir.is_dir() else []), *skill_dir.rglob("test_*")]
                  if f.is_file() for line in f.read_text(encoding="utf-8", errors="ignore").splitlines(True)]
    test_text = "".join(line for line in test_lines if not re.match(r"\s*(import|from)\s", line))
    # `import used as U` names the module U, so a use of `U.` counts as a use of `used`.
    aliases = {}
    for line in test_lines:
        for stem, alias in re.findall(r"^\s*import\s+(\w+)\s+as\s+(\w+)", line):
            aliases.setdefault(stem, []).append(alias)

    def exercised(stem):
        return re.search(rf"\b{re.escape(stem)}\b", test_text) is not None or any(re.search(rf"\b{a}\.", test_text) for a in aliases.get(stem, []))
    untested = [str(f.relative_to(skill_dir)) for f in files if f.relative_to(skill_dir).parts[0] == "scripts"
                and f.suffix in SCRIPT_SUFFIXES and not f.name.startswith("test_") and not exercised(f.stem)]
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    return {
        "skill": skill_dir.name,
        "files": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "skill_lines": len(skill_md.splitlines()),
        "desc_words": _fleet.description_words(skill_md),
        "unref": unref,
        "uncalled": uncalled,
        "unloaded": unloaded,
        "untested": untested,
    }


def weight_table(skill_dirs):
    """Ranked rows: most unreferenced files first, then the larger skill."""
    rows = [weight_row(d) for d in skill_dirs]
    return sorted(rows, key=lambda r: (-len(r["unref"]), -r["bytes"], r["skill"]))


ROUTE_ROW_FILE = re.compile(r"`((?:references|modes|assets)/[^`\s]+\.md)`")
HEAVY_ROUTE_WORDS = 2000   # measured on the fleet: the median route row loads 786 words, and 7 of 37 rows pass 2000


def route_rows(skill_dir):
    """[(words, files, row text)] for each table row or bullet of SKILL.md that names a reference file. The words are the
    size of the files that row loads together."""
    out = []
    for line in (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines():
        files = ROUTE_ROW_FILE.findall(line) if line.startswith(("|", "- ", "* ")) else []
        if files:
            words = sum(len((skill_dir / f).read_text(encoding="utf-8", errors="ignore").split())
                        for f in files if (skill_dir / f).is_file())
            label = line.strip("| ").split("|")[0].strip() if line.startswith("|") else line[2:].split("`")[0].strip(" :")
            out.append((words, files, label))
    return out


def print_route_report(skill_dirs):
    """Report only. A heavy row loads two or more files past the word budget, or one file past it, on a single task."""
    heavy = [(w, d.name, task, files) for d in skill_dirs for w, files, task in route_rows(d) if w > HEAVY_ROUTE_WORDS]
    print(f"Route rows that load more than {HEAVY_ROUTE_WORDS} words for one task:")
    for words, skill, task, files in sorted(heavy, reverse=True):
        print(f"  {words:>5} words  {skill}: {task[:70]}  ({len(files)} file(s))")
    print(f"{len(heavy)} heavy route row(s). A row that bundles setup with the work should split on a one-line check.")


def print_weight_table(rows):
    head = f"{'skill':34} {'files':>5} {'KB':>6} {'skill-lines':>11} {'desc-words':>10} {'unref':>5} {'uncalled':>8} {'unloaded':>8} {'untested':>8}"
    print(head)
    for r in rows:
        print(f"{r['skill'][:34]:34} {r['files']:>5} {r['bytes'] / 1024:>6.1f} {r['skill_lines']:>11} {r['desc_words']:>10} "
              f"{len(r['unref']):>5} {len(r['uncalled']):>8} {len(r['unloaded']):>8} {len(r['untested']):>8}")
    print(f"\n{len(rows)} skill(s). Scripts no test file names, by skill:")
    for r in rows:
        if r["untested"]:
            print(f"  {r['skill']}: {', '.join(r['untested'])}")
    print("Unreferenced files by skill:")
    for r in rows:
        if r["unref"]:
            print(f"  {r['skill']}: {', '.join(r['unref'])}")
