#!/usr/bin/env python3
"""Static scan for dangling skill and file references, plus the weight table.

Two dangling-reference checks run by default and block a commit:
  - dangling-skill-reference (SKILL-REF-1): a skill named as a skill that resolves to no real
    skill. A removed or retitled sibling skill leaves exactly this behind.
  - dangling-file-reference (SKILL-FILE-REF-1): a backticked file name or run
    script that a skill's text cites and its own folder does not hold. A removed or never-declared file
    leaves exactly this behind, and the agent that loads the skill guesses or stalls.

Description cap (SKILL-DESC-1): a skill whose `description` runs over 150 words fails, since every
description loads in every session. Writing quality is judged against the voice file, which no script can check.

Trigger phrases (SKILL-TRIGGER-1): the quoted phrases after "Trigger on" in a description load that skill, so two skills
listing one phrase (case-insensitive, trimmed) fail, and the finding names both skills and the phrase.

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
A file counts as named when another file holds its file name, its module stem for a script, or
a `<folder>/<placeholder>` pattern for its folder. The table sorts by `unref`, then size. A README,
DECISIONS.md and test files never count as unreferenced.

Usage:
    check_skill_structure.py                 # scan every skill under the fleet root
    check_skill_structure.py <path-or-dir>   # scan one folder
    check_skill_structure.py --weight        # print the ranked weight table, then exit
    check_skill_structure.py --routes        # route rows that load more than 2,000 words for one task
    check_skill_structure.py --baseline      # also run the mechanical baseline rules 1, 2, 3, 5, 6, 8, 12, 16 and 17
Tests: python3 -m unittest test_check_skill_structure   (from this scripts/ folder)
"""

import os
import re
import sys
from pathlib import Path

import _fleet
from portability import PLACEHOLDER_USERS, SAFE_EMAIL

SKILLS_ROOT = _fleet.FLEET_ROOT
DESCRIPTION_WORD_LIMIT = 150
_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
# A strong shape says "this is a skill": the word skill beside the name, or the install path.
STRONG_REF_RES = [
    re.compile(rf"`({_NAME})`\s+skill"),
    re.compile(rf"\bskills?\s+`({_NAME})`"),
    re.compile(rf"\.claude/skills/({_NAME})"),
    re.compile(rf"`skills/({_NAME})(?:/SKILL\.md)?`"),
]


def find_skill_dirs():
    return _fleet.find_skills(SKILLS_ROOT)


# A quote opens at a word edge and closes at one, so the apostrophe in 'review tonight's work' stays inside the phrase.
TRIGGER_PHRASE_RE = re.compile(r"(?<!\w)(['\"])(.+?)\1(?!\w)")


def trigger_phrases(skill_md_text):
    """The lower-cased, trimmed quoted phrases that follow "Trigger on" in a skill's description."""
    desc = " ".join(_fleet.description_text(skill_md_text).split())
    _, found, tail = desc.partition("Trigger on")
    return {m.group(2).strip().lower() for m in TRIGGER_PHRASE_RE.finditer(tail)} if found else set()


def trigger_clash_scan(skill_dirs):
    """Return {skill: [(phrase, other skill)]} for each trigger phrase that another scanned skill also lists."""
    owners = {}
    for d in skill_dirs:
        for phrase in trigger_phrases((d / "SKILL.md").read_text(encoding="utf-8")):
            owners.setdefault(phrase, []).append(d.name)
    clashes = {}
    for phrase, names in owners.items():
        for n in names if len(names) > 1 else []:
            clashes.setdefault(n, []).extend((phrase, o) for o in names if o != n)
    return clashes


def extra_skill_dirs(argv, skill_dirs):
    """Skills of each `--with=<dir>` folder, for the trigger comparison only. A copy of a scanned skill (same real folder
    or same SKILL.md text) counts once, and a missing folder is skipped."""
    seen = {d.resolve() for d in skill_dirs}
    texts = {d.name: (d / "SKILL.md").read_text(encoding="utf-8") for d in skill_dirs}
    extra = []
    for arg in argv:
        if not arg.startswith("--with="):
            continue
        root = Path(arg.split("=", 1)[1]).expanduser()
        for d in _fleet.find_skills(root) if root.is_dir() else []:
            if d.resolve() in seen or texts.get(d.name) == (d / "SKILL.md").read_text(encoding="utf-8"):
                continue
            extra.append(d)
    return extra


def skill_ref_scan(skill_dirs):
    """Return {skill: {name}} for each name a skill cites as a skill that no folder in the scanned fleet holds."""
    fleet = {d.name for d in skill_dirs}
    dangling = {}
    for d in skill_dirs:
        files = [d / "SKILL.md"]
        refs = d / "references"
        if refs.is_dir():
            files.extend(sorted(refs.glob("*.md")))
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for rx in STRONG_REF_RES:
                for m in rx.finditer(text):
                    name = m.group(1)
                    if name == d.name:
                        continue
                    if name not in fleet:
                        dangling.setdefault(d.name, set()).add(name)
    return dangling


# SKILL-FILE-REF-1: a skill travels alone, so every file of its own that its text names must sit inside
# its folder. A name found only in another skill passes nowhere. A skill's own files sit in these
# folders, so a path starting anywhere else names a file of the repo the skill works on.
SKILL_FOLDERS = {"references", "scripts", "assets", "modes", "templates", "examples", "agents", "tests", "lib", "bin", "data"}
# Files of the repo a skill works on, which a skill names by bare name and never holds.
OUTSIDE_FILES = {"AGENTS.md", "BACKLOG.md", "CHANGELOG.md", "CLAUDE.md", "CONTEXT.md", "DECISIONS.md",
                 "README.md", "VOICE.md", "backlog-config.json", "package.json"}
FILE_REF_RE = re.compile(r"`([^`\n]+?\.(?:md|py|json|js|sh))`")
# `python3 "$S/check_pages.py"` and `node scripts/build_plan.js`, where `$S` stands for `scripts`.
RUN_REF_RE = re.compile(r"\b(?:python3|node|bash)\s+\"?([^\s\"`]+\.(?:py|js|sh))")


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


from skill_weight import (  # noqa: E402,F401
    HEAVY_ROUTE_WORDS, ROUTE_ROW_FILE, SCRIPT_SUFFIXES, WEIGHT_EXEMPT_NAMES, WEIGHT_SKIP_DIRS, print_route_report,
    print_weight_table, route_rows, skill_files, weight_row, weight_table)

# Baseline rules (skill-creation "Baseline"), checked only with --baseline. Each finding reads `file:line note`.
OC_SKILLS = Path(__file__).resolve().parents[2]   # OliverCode's own skills/ folder, whose skills may read $OC/
BASELINE_SUFFIXES = {".md", ".py", ".js", ".json", ".sh", ".txt", ".example"}
BASELINE_SKIP_DIRS = {"tests", "fixtures", "example", "examples", "__pycache__"}
HOME_PATH_RES = [re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)/"), re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}([A-Za-z0-9._-]+)\\")]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PARENT_RE = re.compile(r"(?<![\w.])((?:\.\./)+[\w./-]+)")   # a bare `../` in prose is a mention, not a read
OTHER_SKILL_RE = re.compile(r"(?:\$\{?OC\}?|~|/)[^\s`'\"]*?skills/([\w.-]+)/(?:scripts/|\.env\.local)")
HISTORY_RES = [re.compile(r"\b(?:DECISIONS?|SPEC|ACT)-\d+\b"), re.compile(r"\b(?:story|issue|PR) #\d+", re.I),
               re.compile(r"^##\s+(?:Known gaps|Change ?log)\b", re.I)]
# Example people other than the three the baseline allows (Jane Doe, John Smith, Sally May). Stored in lower case and
# title-cased at match time, so this file does not name them in text.
SAMPLE_NAMES = ["john doe", "jane smith", "alice", "bob", "charlie", "carol", "dave", "mary smith", "joe bloggs"]
SAMPLE_NAME_RE = re.compile(r"\b(?:" + "|".join(n.title() for n in SAMPLE_NAMES) + r")\b")
VERSION_SUFFIX_RE = re.compile(r"[-_](?:v\d+|\d{1,3}|ticket-?\d+|issue-?\d+)$", re.I)
NAME_EXEMPT_RE = re.compile(r"\d{4}[-_]\d{1,2}|\d{8}|(?:utf|sha|md|base|iso|py|python|node)[-_]?\d+$", re.I)


def baseline_files(skill_dir):
    return [p for p in skill_files(skill_dir)
            if not (BASELINE_SKIP_DIRS & set(p.relative_to(skill_dir).parts[:-1])) and not p.name.startswith("test_")]


STEP_RE = re.compile(r"^\d+\. ", re.M)
SCRIPT_RE = re.compile(r"`[^`]*\.(?:py|sh|js)\b[^`]*`|`(?:python3|bash|node|gh|git)\b")
UNSCRIPTED_MIN_STEPS = 4
UNSCRIPTED_MAX_SHARE = 0.25


def unscripted_procedure(skill_md):
    """(steps, scripted) when a SKILL.md that ships scripts lists numbered steps and few name a script or command, else None."""
    body = re.sub(r"```.*?```", "", skill_md.split("---", 2)[-1], flags=re.S)
    steps = [m.start() for m in STEP_RE.finditer(body)]
    if len(steps) < UNSCRIPTED_MIN_STEPS:
        return None
    chunks = [body[a:b] for a, b in zip(steps, steps[1:] + [len(body)])]
    scripted = sum(1 for c in chunks if SCRIPT_RE.search(c.split("\n\n")[0]))
    return (len(steps), scripted) if scripted / len(steps) < UNSCRIPTED_MAX_SHARE else None


# Rule 17 (token-free by default). A line that says a recurring run (scheduled, recurring, nightly, hourly, daily, weekly,
# every N minutes or hours, heartbeat, poll) starts a session, agent, subagent or model is a finding, unless the SKILL.md
# names a gate command anywhere: the word "gate", as in "run the gate command first".
RECURRING_RE = re.compile(r"\b(?:scheduled|recurring|nightly|hourly|daily|weekly|heartbeat|polls?|polling|every \d+ (?:minutes?|hours?))\b", re.I)
STARTS_MODEL_RE = re.compile(r"\b(?:start|starts|launch|launches|spawn|spawns|open|opens|run|runs)\b[^.\n]{0,40}\b(?:session|agent|subagent|model)s?\b", re.I)
GATE_RE = re.compile(r"\bgate\b", re.I)
NO_MODEL_RE = re.compile(r"\b(?:no|without an?|never starts? an?|zero)\s+(?:model|session|agent|subagent)s?\b(?:\s+call)?", re.I)


def ungated_recurring_run(skill_md):
    """Line number of the first line that has a recurring run start a model, when the SKILL.md names no gate command, else None."""
    if GATE_RE.search(skill_md):
        return None
    body_start = skill_md.count("\n", 0, len(skill_md) - len(skill_md.split("---", 2)[-1])) if skill_md.startswith("---") else 0
    for n, line in enumerate(skill_md.splitlines(), 1):
        if n > body_start and RECURRING_RE.search(line) and STARTS_MODEL_RE.search(NO_MODEL_RE.sub("", line)):
            return n
    return None


def baseline_findings(skill_dir):
    """[(rule, note)] for the mechanical baseline rules over one skill folder."""
    out, files = [], baseline_files(skill_dir)
    inside_oc = skill_dir.resolve().is_relative_to(OC_SKILLS.resolve())
    skill_root = os.path.normpath(skill_dir.resolve())
    for f in files:
        rel = f.relative_to(skill_dir).as_posix()
        stems = [skill_dir.name] if f.parent == skill_dir and f.name == "SKILL.md" else []
        stems += [part.rsplit(".", 1)[0] if i == len(f.relative_to(skill_dir).parts) - 1 else part
                  for i, part in enumerate(f.relative_to(skill_dir).parts)]
        for stem in stems:
            if VERSION_SUFFIX_RE.search(stem) and not NAME_EXEMPT_RE.search(stem):
                out.append(("baseline-name-suffix", f"{rel} name `{stem}` ends in a version, number or ticket suffix"))
                break
        if f.suffix not in BASELINE_SUFFIXES:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            where = f"{rel}:{n}"
            for rx in HOME_PATH_RES:
                for u in rx.findall(line):
                    if u not in PLACEHOLDER_USERS:
                        out.append(("baseline-local-path", f"{where} absolute home path of `{u}`"))
            for a in EMAIL_RE.findall(line):
                if not SAFE_EMAIL.search(a.rstrip(".")):
                    out.append(("baseline-local-path", f"{where} personal email address"))
            for tok in PARENT_RE.findall(line):
                target = os.path.normpath(os.path.join(f.resolve().parent, tok))
                if target != skill_root and not target.startswith(skill_root + os.sep):
                    out.append(("baseline-outside-read", f"{where} `{tok}` leaves the skill folder"))
            for other in ([] if inside_oc else OTHER_SKILL_RE.findall(line)):
                if other != skill_dir.name:
                    out.append(("baseline-outside-read", f"{where} reads files of the `{other}` skill"))
            if any(rx.search(line) for rx in HISTORY_RES):
                out.append(("baseline-history-note", f"{where} decision or ticket ID or change-log text"))
            for m in SAMPLE_NAME_RE.findall(line):
                out.append(("baseline-sample-name", f"{where} sample name `{m}`"))
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    has_setup = any("setup" in p.name.lower() for p in files if p.relative_to(skill_dir).parts[0] in ("modes", "references")) \
        or re.search(r"^#+.*Setup", skill_md, re.M)
    if any(p.name == ".env.local.example" for p in files) and not has_setup:
        out.append(("baseline-setup-missing", "SKILL.md ships `.env.local.example` and has no setup mode"))
    ships_scripts = any(p.suffix in (".py", ".sh", ".js") and p.relative_to(skill_dir).parts[0] == "scripts" for p in files)
    gap = unscripted_procedure(skill_md) if ships_scripts else None
    if gap:
        out.append(("baseline-unscripted-procedure", f"SKILL.md lists {gap[0]} numbered steps and only {gap[1]} name a script or command"))
    line = ungated_recurring_run(skill_md)
    if line:
        out.append(("baseline-ungated-recurring-run", f"SKILL.md:{line} starts a model on a recurring run and names no gate command"))
    return out


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

    dangling = skill_ref_scan(skill_dirs)
    findings = {
        n: [("dangling-skill-reference", f"`{x}` names no skill in this fleet")
            for x in sorted(names)]
        for n, names in dangling.items()
    }
    for n, tokens in file_ref_scan(skill_dirs).items():
        findings.setdefault(n, []).extend(
            ("dangling-file-reference", f"`{x}` matches no file in this fleet") for x in sorted(tokens))
    scanned = {d.name for d in skill_dirs}
    for n, pairs in trigger_clash_scan(skill_dirs + extra_skill_dirs(argv, skill_dirs)).items():
        if n not in scanned:
            continue
        findings.setdefault(n, []).extend(
            ("duplicate-trigger-phrase", f'"{p}" is also a trigger phrase of {o}') for p, o in sorted(pairs))
    for d in skill_dirs:
        words = _fleet.description_words((d / "SKILL.md").read_text(encoding="utf-8"))
        if words > DESCRIPTION_WORD_LIMIT:
            findings.setdefault(d.name, []).append(
                ("description-over-cap", f"description is {words} words (cap {DESCRIPTION_WORD_LIMIT})"))

    if "--baseline" in argv:
        for d in skill_dirs:
            found = baseline_findings(d)
            if found:
                findings.setdefault(d.name, []).extend(found)

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
