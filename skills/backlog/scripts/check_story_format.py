#!/usr/bin/env python3
"""Check that an issue body follows references/story-template.md.

Usage: check_story_format.py [BODY_FILE|-] [--kind story|epic] [--title TITLE] [--offline]
Reads the body from BODY_FILE, or from stdin when the file is omitted or "-". Prints each
missing part with its fix and exits 1 when any part is missing, 0 when the body is complete,
2 on a usage error. A story also lists each open story whose Files area shares a file or folder
with it, read once through gh; `--offline` skips that read (#1274).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

STORY_SENTENCE = re.compile(r"\bAs (?:the|an?)\s+[^,\n]+?,?\s+I want\s+.+?,\s*so that\s+\S", re.I | re.S)
EPIC_LINE = re.compile(r"^\s*Epic:\s*(?:[\w.-]+/[\w.-]+)?#\d+\s*$", re.M)
BLOCKER_LINE = re.compile(r"^\s*(?:[-*]\s*)?Blocked by:\s*(?:none\b|(?:[\w.-]+/[\w.-]+)?#\d+)", re.I | re.M)
FENCE = re.compile(r"^\s*```.*?^\s*```", re.M | re.S)
LINE_NUMBER = re.compile(r"\blines? \d+\b|[\w/.-]+\.(?:py|sh|md|js|ts|tsx|jsx|json|ya?ml|go|rb|rs|java|c|h|cpp|txt):\d+\b", re.I)
PRIORITY = re.compile(r"\bPriority:\s*(\S+?)[.,;\s]", re.I)
SIZE = re.compile(r"\bSize:\s*(\S+?)[.,;\s]", re.I)
WORK_TYPE = re.compile(r"\bWork type:\s*(\w+)", re.I)
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z /|-]*>")
COVERAGE_LINE = re.compile(r"^\s*(?:[-*]\s*)?Existing coverage checked:\s*\S", re.I | re.M)
STEP = re.compile(r"^\s*(Given|When|Then|And|But)\b", re.I)
COVERAGE_TEXT = re.compile(r"^\s*(?:[-*]\s*)?Existing coverage checked:(.*)$", re.I | re.M)
AREA = re.compile(r"^\W*Files area:\W*(.+)$", re.I | re.M)
FIELDS_LINE = r"^(?=(?:Priority|Size|Work type):)"  # a story's own fields start their line (#1514)
FIT_LINE = re.compile(r"^[ \t*-]*Fit:[ \t*]*\S", re.I | re.M)
SECOND_OPINION = re.compile(r"\bsecond[- ]opinion[\s:,]+(?:(?:dis)?agreed|differed|skipped)\b", re.I)
ASK_TEXT = re.compile(r"\bAs (?:the|an?)\s.*?\bI want\s+(.*?)(?=,?\s*\bso that\b|\n\s*\n|\Z)", re.I | re.S)
SCENARIO_LINE = re.compile(r"^\s*(?:Scenario(?: Outline)?:|Given\b|When\b|Then\b|And\b|But\b).*$", re.M)
QUOTED = re.compile(r'"[^"\n]*"|`[^`\n]*`')
LINE_TARGET = re.compile(r"\b(?:under|below|within|(?:fewer|less|no more) than|at most|(?:in|to) (?:about|around|roughly))\s+"
                         r"(?:(?:about|around|roughly)\s+)?~?\d[\d,]*\s+lines?\b|\b\d[\d,]*\s+lines?\s+or\s+(?:fewer|less)\b", re.I)
# shortcut: word lists, so other words ("delete", "drop") pass, and a sentence ending "tries to remove tests" or "when its
# tests are removed" is refused; tighten them when either is filed. The code noun is the verb's object or subject, so a bug
# where code removes something else passes.
CODE_NOUN = r"(?:code|modules?|scripts?|functions?|helpers?|commands?|hooks?|features?|tests?|lines|duplicat\w*)\b"
OBJECT = r"(?:\s+(?!(?:before|after|when|while|if|because|from|until|unless|that|which)\b)[\w'-]+,?){0,4}?\s+" + CODE_NOUN
NOUN_ENDS = r"(?=\s*(?:$|[,.;:]|(?:and|down|from|in|into|to|with)\b))"  # so "test" in "test worktrees" is not the noun
SHRINK = re.compile(
    # leading: "Remove the dead helpers", "Removing the dead helpers", "Tests: consolidation of the test helpers"
    r"^(?:[\w-]+:\s*)?(?:to\s+)?(?:remov(?:es?|ing|al\s+of)|cut(?:s|ting)?|shrink(?:s|ing)?|merg(?:es?|ing)"
    r"|consolidat(?:es?|ing|ion\s+of))\b" + OBJECT
    # asked of someone: "OliverCode to remove the unused commands"
    + r"|\bto\s+(?:remove|cut|shrink|merge|consolidate)\b" + OBJECT + NOUN_ENDS
    # the result: "unused features are removed", "the dead code to be removed", "the drain module to shrink"
    + r"|\b" + CODE_NOUN + r"(?:\s+files)?(?:\s+(?:should|must|can|will|to))?(?:\s+(?:are|is|be|being|gets?))?(?:\s+\w+ly)?"
    r"\s+(?:removed|cut|merged|consolidated|shrunk|shrinks?)" + NOUN_ENDS, re.I)
TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__|fixtures)/|(?:^|/)test_[^/]*$|[._](?:test|spec)\.\w+$")
REMOVES_TESTS = re.compile(r"^\W*Removes tests:", re.I | re.M)

PRIORITIES = ("P0", "P1", "P2")
SIZES = ("XS", "S", "M", "L", "XL")
MAX_FILES = 5
WORK_TYPES = ("Story", "Epic")

TEMPLATE = "references/story-template.md"


def gherkin_problems(body):
    """Return problems with the Feature and Scenario blocks, each as (part, fix)."""
    lines = body.splitlines()
    if not any(re.match(r"^\s*Feature:\s*\S", l) for l in lines):
        return [("Gherkin Feature", "add a `Feature: <name>` line inside a ```gherkin fence, as in " + TEMPLATE)]
    scenarios, current = [], None
    for line in lines:
        m = re.match(r"^\s*Scenario(?: Outline)?:\s*(.*)$", line)
        if m:
            current = {"name": m.group(1).strip() or "(unnamed)", "steps": []}
            scenarios.append(current)
            continue
        s = STEP.match(line)
        if s and current is not None:
            current["steps"].append(s.group(1).title())
    if not scenarios:
        return [("Gherkin Scenario", "add at least one `Scenario: <name>` with Given, When and Then lines")]
    problems = []
    for sc in scenarios:
        kinds = [k for k in sc["steps"] if k in ("Given", "When", "Then")]
        missing = [k for k in ("Given", "When", "Then") if k not in kinds]
        if missing:
            problems.append((f"Scenario \"{sc['name']}\" lacks {', '.join(missing)}",
                             f"give every scenario a Given, a When and a Then line"))
        elif kinds.index("Given") > kinds.index("When") or kinds.index("When") > kinds.index("Then"):
            problems.append((f"Scenario \"{sc['name']}\" steps are out of order",
                             "write the steps in the order Given, When, Then"))
    return problems


def field(pattern, body):
    """The pattern's match on a fields line, else its first one, since a scenario may quote another story's fields."""
    return re.search(FIELDS_LINE + ".*?" + pattern.pattern, body, re.M | re.I) or pattern.search(body)


def kind_of(body, kind=None):
    """The kind a body is checked as: the one asked for, else its Work type line, else a story."""
    wt = field(WORK_TYPE, body)
    return (kind or (wt.group(1) if wt else "Story")).capitalize()


def files_of(body):
    """The entries on the Files area line, Markdown punctuation stripped."""
    area = AREA.search(body)
    return [e for e in (t.strip("`.,;*()") for t in re.split(r"[,;\s]+", area.group(1))) if e] if area else []


def shares_files(mine, theirs):
    """True when a path in `mine` is a path in `theirs`, or one is a folder that holds the other (#1274).
    A word with no slash or dot is not a path, so it never overlaps another story."""
    paths = lambda entries: [x.rstrip("/") for x in entries if re.search(r"[/.]", x)]  # noqa: E731
    for a in paths(mine):
        for b in paths(theirs):
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


def open_stories(root):
    """{number: {"title", "body"}} of the open issues of the repo at `root`, read once through gh REST (#1274).
    Raises RuntimeError when gh cannot read them."""
    try:
        done = subprocess.run(["gh", "api", "repos/{owner}/{repo}/issues?state=open&per_page=100", "--paginate", "--jq",
                               '.[] | select(has("pull_request") | not) | {number, title, body}'],
                              capture_output=True, text=True, cwd=root, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(str(e) or e.__class__.__name__) from e
    if done.returncode:
        raise RuntimeError(done.stderr.strip()[:120] or "gh api failed")
    return {o["number"]: o for o in (json.loads(line) for line in done.stdout.splitlines() if line.strip())}


def overlap_problems(body, stories):
    """(part, fix) for each open story in `stories` ({number: {"title", "body"}}) that shares a Files area path with the body.
    The body passes an overlap only when its Existing coverage checked line names that story's number (#1274)."""
    mine = files_of(body)
    coverage = COVERAGE_TEXT.search(body)
    named = set(re.findall(r"#(\d+)", coverage.group(1))) if coverage else set()
    problems = []
    for number, story in sorted(stories.items()):
        if str(number) in named or not shares_files(mine, files_of(story.get("body") or "")):
            continue
        problems.append((f"Open story #{number} \"{story.get('title') or ''}\" touches the same files",
                         f"add the new scenarios to #{number}, or name #{number} in `Existing coverage checked:` and say why this work is separate"))
    return problems


def paths_of(body):
    """The Files area paths the size limits count. A note in brackets and a joining word are not paths, and a word with
    no slash or dot counts only when it stands alone, as `Makefile` does (#1437)."""
    area = AREA.search(body)
    text = re.sub(r"(?<!\S)\([^()]*\)", " ", area.group(1)) if area else ""
    paths = set()
    # shortcut: extensionless files separated by spaces alone are not counted, split on them when a story files that
    for item in re.split(r"[,;]|(?<!\S)(?:and|plus|&)(?!\S)", text):
        words = [w for w in (t.strip("`.,;*()") for t in item.split()) if w]
        paths.update(w for w in words if len(words) == 1 or re.search(r"[/.]", w))
    return paths


def size_problems(body, size, title=""):
    """(part, fix) for each way a story is too large for the drain to build and land (#1437)."""
    problems = []
    if size in ("L", "XL"):
        problems.append((f"Size {size} is too large for a Story",
                         "a Story is S or M at most, and the work becomes an Epic over S and M stories split by file group"))
    entries = paths_of(body)
    if len(entries) > MAX_FILES:
        problems.append((f"Files area names {len(entries)} files", "split it into stories of five files or fewer, one fix each"))
    target = LINE_TARGET.search(QUOTED.sub("", "\n".join(SCENARIO_LINE.findall(body))))
    if target:
        problems.append((f"Line target \"{target.group(0)}\" in a scenario",
                         "state the behavior to keep, one module per story, with no line target"))
    ask = ASK_TEXT.search(body.replace("*", ""))
    if size == "M" and any(SHRINK.search(text.strip()) for text in (title, ask.group(1) if ask else "")):
        problems.append(("Size M for a story that shrinks or removes code", "file one S story per module"))
    outside = sorted(e for e in entries if not TEST_PATH.search(e))
    if REMOVES_TESTS.search(body) and outside:
        problems.append((f"Removes tests: story also changes {', '.join(outside)}",
                         "remove the tests in their own story, whose Files area names only test files"))
    return problems


def check_body(body, kind=None, coverage=True, blocker=False, line_numbers=False, root=None, files=False, fit=False, title=""):
    """Return a list of (missing part, fix) for the body. An empty list means it is complete.

    `coverage=False` skips the Existing coverage checked line, for a scan of stories filed before it was required.
    `blocker=True` requires the Blocked by line and `line_numbers=True` flags a line number; the command sets both,
    and the library default leaves them off so intake's scan and the generated bodies are judged as they were.
    `files=True` requires the Files area line of a story, which dispatch needs; the command sets it (#1274).
    `root` is the repo the story changes, so a Files area entry that is a folder there is named.
    `fit=True` requires a story's Fit line and a second-opinion result on its coverage line; the command and bug intake set it.
    A story's size limits always apply, and the shrink rule reads `title` and what the story sentence asks for (#1437).
    """
    problems = []
    wt = field(WORK_TYPE, body)
    work_type = wt.group(1).capitalize() if wt else None
    kind = kind_of(body, kind)

    if not STORY_SENTENCE.search(body.replace("*", "")):
        problems.append(("User story sentence",
                         "start with `**As the <role>**, I want <the ask>, so that <the outcome>.`"))
    problems += gherkin_problems(body)
    if kind == "Story" and not EPIC_LINE.search(body):
        problems.append(("Epic link", "add a line `Epic: #<number>` naming the epic this story belongs to; "
                                      "pick or create one first"))
    if blocker and kind == "Story" and not BLOCKER_LINE.search(body):
        problems.append(("Blocked by line", "add `Blocked by: none.` or `Blocked by: #<number>` naming the story "
                                            "that must land first, as in " + TEMPLATE))
    if coverage and kind == "Story" and not COVERAGE_LINE.search(body):
        problems.append(("Existing coverage checked line",
                         "add `Existing coverage checked:` naming the code, doc or issue you searched and what you found, as in " + TEMPLATE))
    if fit and kind == "Story":
        if not FIT_LINE.search(body):
            problems.append(("Fit line", "add `Fit:` answering the fit check, as in " + TEMPLATE))
        covered = COVERAGE_TEXT.search(body)
        if covered and not SECOND_OPINION.search(covered.group(1)):
            problems.append(("Second-opinion result", "add `second opinion agreed`, `differed` or `skipped` and why to the "
                                                      "`Existing coverage checked:` line, as in " + TEMPLATE))
    p = PRIORITY.search(body + " ")
    if not p:
        problems.append(("Priority", "add `Priority: P0`, `P1` or `P2`"))
    elif p.group(1).upper() not in PRIORITIES:
        problems.append((f"Priority \"{p.group(1)}\" is not valid", "use P0, P1 or P2"))
    s = field(SIZE, body + " ")
    if not s:
        problems.append(("Size", "add `Size: XS`, `S`, `M`, `L` or `XL`"))
    elif s.group(1).upper() not in SIZES:
        problems.append((f"Size \"{s.group(1)}\" is not valid", "use XS, S, M, L or XL"))
    if not wt:
        problems.append(("Work type", "add `Work type: Story` or `Work type: Epic`"))
    elif work_type not in WORK_TYPES:
        problems.append((f"Work type \"{wt.group(1)}\" is not valid", "use Story or Epic"))
    elif work_type != kind:
        problems.append((f"Work type is {work_type} but this body is checked as a {kind.lower()}",
                         f"set `Work type: {kind}`"))
    if files and kind == "Story" and not AREA.search(body):
        problems.append(("Files area", "add a `Files area:` line naming the files the story changes, not a folder, as in " + TEMPLATE))
    if kind == "Story":
        problems += size_problems(body, s.group(1).upper() if s else "", title)
    for entry in files_of(body):
        if entry.endswith("/") or (root is not None and (Path(root) / entry).is_dir()):
            problems.append((f"Files area names the folder {entry}",
                             "name the files the story changes, because a folder holds back every story that touches a file inside it"))
    ln = LINE_NUMBER.search(FENCE.sub("", body)) if line_numbers else None
    if ln:
        problems.append((f"Line number \"{ln.group(0)}\" in the body",
                         "name the function, section or file instead, because a line number goes stale at the next commit"))
    ph = PLACEHOLDER.search(re.sub(r"`[^`]*`", "", body))
    if ph:
        problems.append((f"Unfilled placeholder {ph.group(0)}", "replace every <...> with the real text"))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("body_file", nargs="?", default="-", help="issue body file, or - for stdin")
    ap.add_argument("--kind", choices=("story", "epic"), help="check as this kind; default reads Work type")
    ap.add_argument("--title", default="", help="issue title, read by the size check")
    ap.add_argument("--offline", action="store_true", help="skip the read of open stories that lists the overlaps")
    args = ap.parse_args(argv)
    try:
        body = sys.stdin.read() if args.body_file == "-" else open(args.body_file, encoding="utf-8").read()
    except OSError as e:
        print(f"Cannot read the body: {e}", file=sys.stderr)
        return 2
    if not body.strip():
        print("The body is empty. Write it from " + TEMPLATE + ".", file=sys.stderr)
        return 1
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = (top.stdout.strip() or None) if top.returncode == 0 else None
    problems = check_body(body, args.kind, blocker=True, line_numbers=True, files=True, root=root, fit=True, title=args.title)
    if not args.offline and kind_of(body, args.kind) == "Story":
        try:
            problems += overlap_problems(body, open_stories(root))
        except RuntimeError as e:
            problems.append(("Overlap check", f"the open stories could not be read ({e}), so this story cannot be checked against them; "
                                              "run it again once gh can reach GitHub"))
    for part, fix in problems:
        print(f"MISSING {part}. Fix: {fix}")
    if problems:
        return 1
    print("Story format complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
