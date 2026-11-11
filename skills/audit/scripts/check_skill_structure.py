#!/usr/bin/env python3
"""Static scan for dangling skill and file references, plus the weight table.

Two dangling-reference checks run by default and block a commit:
  - dangling-skill-reference (SKILL-REF-1): a skill named as a skill that resolves to no real
    skill. A removed or retitled sibling skill leaves exactly this behind.
  - dangling-file-reference (SKILL-FILE-REF-1): a backticked file name or run
    script that a skill's text cites and its own folder does not hold. A removed or never-declared file
    leaves exactly this behind, and the agent that loads the skill guesses or stalls.
It also prints the in-family and cross-family reference counts. Both counts are information,
never findings.

Description cap (SKILL-DESC-1): a skill whose `description` runs over 150 words fails, since every
description loads in every session. Writing quality is judged against the voice file, which no script can check.

Weight pass (SKILL-WEIGHT-1): `--weight` prints one ranked table of every skill with the
counts that suggest excess. It makes no judgment. It is the candidate list for a read of
each skill. The columns are:
  files, KB          every file in the skill folder, and their total size
  skill-lines        lines in SKILL.md
  desc-words         words in the `description`
  unref              files no other file in the skill names
  uncalled           scripts no other file in the skill names
  untested           scripts no test file in `<family>/tests/<skill>/` or beside the script names
  unloaded           references/*.md files no other file in the skill names
  in-fam, cross-fam  skill references that stay in the family, and that leave it
A file counts as named when another file holds its file name, its module stem for a script, or
a `<folder>/<placeholder>` pattern for its folder. The table sorts by `unref`, then size. A README,
DECISIONS.md and test files never count as unreferenced.

Usage:
    check_skill_structure.py                 # scan every skill under the fleet root
    check_skill_structure.py <path-or-dir>   # scan one folder
    check_skill_structure.py --weight        # print the ranked weight table, then exit
    check_skill_structure.py --routes        # route rows that load more than 2,000 words for one task
Tests: python3 -m unittest test_check_skill_structure   (from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT
DESCRIPTION_WORD_LIMIT = 150
# Skills that live outside this fleet but are real: whatever is installed on this machine.
# A name that is in neither place is dangling.
EXTERNAL_SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
]
_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
# A strong shape says "this is a skill": the word skill beside the name, or the install path.
STRONG_REF_RES = [
    re.compile(rf"`({_NAME})`\s+skill"),
    re.compile(rf"\bskills?\s+`({_NAME})`"),
    re.compile(rf"\.claude/skills/({_NAME})"),
]
# A verb shape counts a reference to a real skill. It never flags a dangling one: a
# subcommand such as `force-set` has the same shape as a skill name.
VERB_REF_RE = re.compile(
    rf"\b(?:load|invoke|route to|hand off to|defer to|use|run|call|see|per)s?\s+`({_NAME})`", re.I
)


def find_skill_dirs():
    return _fleet.find_skills(SKILLS_ROOT)


def family_of(skill_dir):
    """The family folder a skill sits in, or "" for a skill directly under the fleet root."""
    parent = skill_dir.resolve().parent
    return "" if parent == _fleet.FLEET_ROOT.resolve() or parent == Path(SKILLS_ROOT).resolve() else parent.name


def skill_ref_scan(skill_dirs):
    """Return (dangling, in_family, cross_family), each {skill: {name}}. A name resolves when
    its folder is in this fleet or in EXTERNAL_SKILL_DIRS."""
    fleet = {d.name: family_of(d) for d in skill_dirs}
    external = {c.name for root in EXTERNAL_SKILL_DIRS if root.is_dir() for c in root.iterdir()}
    dangling, in_family, cross_family = {}, {}, {}
    for d in skill_dirs:
        files = [d / "SKILL.md"]
        refs = d / "references"
        if refs.is_dir():
            files.extend(f for f in sorted(refs.glob("*.md")) if not f.name.startswith("CONTEXT-"))
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for rx in STRONG_REF_RES + [VERB_REF_RE]:
                for m in rx.finditer(text):
                    name = m.group(1)
                    if name == d.name:
                        continue
                    if name in fleet:
                        bucket = in_family if fleet[name] == fleet[d.name] else cross_family
                        bucket.setdefault(d.name, set()).add(name)
                    elif name not in external and rx is not VERB_REF_RE:
                        dangling.setdefault(d.name, set()).add(name)
    return dangling, in_family, cross_family


# SKILL-FILE-REF-1: a skill travels alone, so every file of its own that its text names must sit inside
# its folder. A name found only in another skill passes nowhere. A skill's own files sit in these
# folders, so a path starting anywhere else names a file of the repo the skill works on.
SKILL_FOLDERS = {"references", "scripts", "assets", "modes", "templates", "examples", "agents", "tests", "lib", "bin", "data"}
# Files of the repo a skill works on, which a skill names by bare name and never holds.
OUTSIDE_FILES = {"AGENTS.md", "BACKLOG.md", "CHANGELOG.md", "CLAUDE.md", "CONTEXT.md", "DECISIONS.md",
                 "README.md", "VOICE.md", "backlog-config.json", "package.json"}
FILE_REF_RE = re.compile(r"`([^`\n]+?\.(?:md|py|json|js))`")
# `python3 "$S/check_pages.py"` and `node scripts/build_plan.js`, where `$S` stands for `scripts`.
RUN_REF_RE = re.compile(r"\b(?:python3|node)\s+\"?([^\s\"`]+\.(?:py|js))")


def _own_path(token):
    token = token.replace("$S/", "scripts/").replace("$SKILL_DIR/", "")
    while token.startswith(("../", "./")):
        token = token.split("/", 1)[1]
    return token


def file_ref_scan(skill_dirs):
    """Return {skill: {name}} for each file name a skill's text cites that the skill folder does not hold.
    A name with a slash resolves as a path from the skill folder, a bare name by file name inside it."""
    dangling = {}
    for skill in skill_dirs:
        held = [p for p in skill.rglob("*") if p.is_file()]
        names = {p.name for p in held}
        paths = {"/".join(p.relative_to(skill).parts) for p in held}
        names |= {q.rsplit("/", 1)[-1] for q in paths}
        for f in held:
            parts = f.relative_to(skill).parts
            if f.suffix != ".md" or f.name in ("DECISIONS.md", "README.md") or "tests" in parts:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for token in FILE_REF_RE.findall(text) + RUN_REF_RE.findall(text):
                if " " in token or token in OUTSIDE_FILES:
                    continue
                token = _own_path(token)
                if any(c in token for c in "*<>${}()[]") or token.startswith(("http", "~", "/")):
                    continue
                if "/" in token and token.split("/", 1)[0] not in SKILL_FOLDERS | {p.parts[0] for p in map(Path, paths)}:
                    continue  # a path in the repo the skill works on
                found = any(q == token or q.endswith("/" + token) for q in paths) if "/" in token else token in names
                if not found:
                    dangling.setdefault(skill.name, set()).add(token)
    return dangling


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
    _dangling, in_family, cross_family = skill_ref_scan(skill_dirs)
    rows = []
    for d in skill_dirs:
        row = weight_row(d)
        row["in_family"] = len(in_family.get(d.name, ()))
        row["cross_family"] = len(cross_family.get(d.name, ()))
        rows.append(row)
    return sorted(rows, key=lambda r: (-len(r["unref"]), -r["bytes"], r["skill"]))


ROUTE_ROW_FILE = re.compile(r"`((?:references|modes|assets)/[^`\s]+\.md)`")
HEAVY_ROUTE_WORDS = 2000   # measured on the fleet: the median route row loads 786 words, and 7 of 37 rows pass 2000


def route_rows(skill_dir):
    """[(words, files, row text)] for each table row of SKILL.md that names a reference file. The words are the
    size of the files that row loads together."""
    out = []
    for line in (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines():
        files = ROUTE_ROW_FILE.findall(line) if line.startswith("|") else []
        if files:
            words = sum(len((skill_dir / f).read_text(encoding="utf-8", errors="ignore").split())
                        for f in files if (skill_dir / f).is_file())
            out.append((words, files, line.strip("| ").split("|")[0].strip()))
    return out


def print_route_report(skill_dirs):
    """Report only. A heavy row loads two or more files past the word budget, or one file past it, on a single task."""
    heavy = [(w, d.name, task, files) for d in skill_dirs for w, files, task in route_rows(d) if w > HEAVY_ROUTE_WORDS]
    print(f"Route rows that load more than {HEAVY_ROUTE_WORDS} words for one task:")
    for words, skill, task, files in sorted(heavy, reverse=True):
        print(f"  {words:>5} words  {skill}: {task[:70]}  ({len(files)} file(s))")
    print(f"{len(heavy)} heavy route row(s). A row that bundles setup with the work should split on a one-line check.")


def print_weight_table(rows):
    head = f"{'skill':34} {'files':>5} {'KB':>6} {'skill-lines':>11} {'desc-words':>10} {'unref':>5} {'uncalled':>8} {'unloaded':>8} {'untested':>8} {'in-fam':>6} {'cross-fam':>9}"
    print(head)
    for r in rows:
        print(f"{r['skill'][:34]:34} {r['files']:>5} {r['bytes'] / 1024:>6.1f} {r['skill_lines']:>11} {r['desc_words']:>10} "
              f"{len(r['unref']):>5} {len(r['uncalled']):>8} {len(r['unloaded']):>8} {len(r['untested']):>8} {r['in_family']:>6} {r['cross_family']:>9}")
    print(f"\n{len(rows)} skill(s). Scripts no test file names, by skill:")
    for r in rows:
        if r["untested"]:
            print(f"  {r['skill']}: {', '.join(r['untested'])}")
    print("Unreferenced files by skill:")
    for r in rows:
        if r["unref"]:
            print(f"  {r['skill']}: {', '.join(r['unref'])}")


def main(argv=None):
    global SKILLS_ROOT
    argv = sys.argv[1:] if argv is None else argv
    SKILLS_ROOT = _fleet.scan_root(argv, SKILLS_ROOT)
    skill_dirs = find_skill_dirs()
    if "--weight" in argv:
        print_weight_table(weight_table(skill_dirs))
        sys.exit(0)
    if "--routes" in argv:
        print_route_report(skill_dirs)
        sys.exit(0)

    dangling, in_family, cross_family = skill_ref_scan(skill_dirs)
    findings = {
        n: [("dangling-skill-reference", f"`{x}` names no skill in this fleet or in ~/.claude/skills")
            for x in sorted(names)]
        for n, names in dangling.items()
    }
    for n, tokens in file_ref_scan(skill_dirs).items():
        findings.setdefault(n, []).extend(
            ("dangling-file-reference", f"`{x}` matches no file in this fleet") for x in sorted(tokens))
    for d in skill_dirs:
        words = _fleet.description_words((d / "SKILL.md").read_text(encoding="utf-8"))
        if words > DESCRIPTION_WORD_LIMIT:
            findings.setdefault(d.name, []).append(
                ("description-over-cap", f"description is {words} words (cap {DESCRIPTION_WORD_LIMIT})"))
    print(f"Skill references: {sum(map(len, in_family.values()))} in-family across "
          f"{len(in_family)} skill(s), {sum(map(len, cross_family.values()))} cross-family "
          f"across {len(cross_family)} skill(s).\n")

    total = 0
    for name in sorted(findings):
        total += len(findings[name])
        print(f"{name}: {len(findings[name])} likely finding(s)")
        for rule, note in findings[name]:
            print(f"  - [{rule}] {note}")

    if total == 0:
        print("No dangling skill or file references, and every description is within the word cap.")
        sys.exit(0)

    print(f"\n{total} likely finding(s) across {len(findings)} skill(s). Verify each before treating it as a real defect.")
    sys.exit(1)


if __name__ == "__main__":
    main()
