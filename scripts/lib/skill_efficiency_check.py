"""Skill efficiency gate for this repo's own skills/. GATE-SKILL-EFFICIENCY-1 in docs/DECISIONS.md.

Holds every skills/<name>/SKILL.md and its references/*.md to the mechanical rules of
core/contracts/SKILL_EFFICIENCY_STANDARD.md:

  - rule 1, monolith-without-references: a SKILL.md over MONOLITH_WORD_CAP words with no
    references/ folder to split into
  - rule 2, duplicate-paragraph: two paragraphs of MIN_PARAGRAPH_WORDS+ words whose word
    sequences match at SIMILARITY_THRESHOLD or more, across two skills or across two files
    of one skill. Text declared as deliberate reuse in duplication_check.DECLARED_MARKERS
    is removed first, so a convention line every skill carries is not a duplicate
  - rule 5, the six named MCP-call patterns (MCP_RULES)

The thresholds below are the one home for these numbers. The standard points here and
does not restate them.

Ported from the skill-fleet-audit checkers check_skill_structure.py and
check_mcp_patterns.py as they stood when the standard was written. Those scripts later
dropped these rules, so this module is now their only implementation. ASD-STE100 clarity
(rule 3) is the commit hook's Gate 11 and is not repeated here.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from lib.duplication_check import DECLARED_MARKERS, WORD

MONOLITH_WORD_CAP = 1500  # words in one SKILL.md before it must split into references/
MIN_PARAGRAPH_WORDS = 30  # shorter paragraphs overlap by chance and are not compared
SIMILARITY_THRESHOLD = 0.55  # word-level SequenceMatcher ratio that counts as a restatement

MCP_RULES = (
    "no-concise-mode",
    "no-pagination",
    "per-field-search-loop",
    "fuzzy-search-only",
    "no-dry-run-first",
    "no-pick-one-rule",
)

SEARCH_TOOL_RE = re.compile(r"`(\w*_search\w*)`")
FUZZY_SEARCH_RE = re.compile(r"\b(sharepoint_search|\w*folder_search)\b")
DESTRUCTIVE_RE = re.compile(r"\b(sharepoint_upload_file|outlook_send_mail|wb\.save)\b")
DRY_RUN_RE = re.compile(r"dry.?run|copy first|test copy|--file", re.I)
# "search" must be in the phrase: "per field" alone matched a cost-ordered fallback list
# with no search loop in it, a false positive on the fleet run that shaped this rule.
PER_FIELD_RE = re.compile(
    r"\b(separate search per field|one search per field|search per field|per-field search)\b",
    re.I,
)
PER_FIELD_NEGATION_RE = re.compile(r"\bnot\b[^.]{0,20}\b(one|separate|per-field)\b", re.I)
STRATEGY_FLIP_RE = re.compile(r"\btwo (real )?methods exist\b", re.I)
# "direct" as a word: "directory" and "directions" name no direct-path lookup.
DIRECT_LOOKUP_RE = re.compile(r"\bdirect\b", re.I)

LABEL = "  [SKILL EFFICIENCY]"


def skill_dirs(repo_root: Path) -> tuple[list[Path], list[str]]:
    """Skill folders under skills/, and a finding for each folder that holds no SKILL.md.
    A dot-folder such as .fleet-audit holds fleet data, not a skill."""
    root = repo_root / "skills"
    if not root.is_dir():
        return [], []
    dirs, failures = [], []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "SKILL.md").is_file():
            dirs.append(d)
        else:
            failures.append(f"{LABEL} {_rel(d, repo_root)}: no SKILL.md -- a folder in skills/ "
                            f"is a skill, so add its SKILL.md or move the folder out")
    return dirs, failures


def skill_texts(skill_dir: Path) -> list[Path]:
    """SKILL.md, then each references/*.md: the files an invocation can load."""
    refs = skill_dir / "references"
    return [skill_dir / "SKILL.md", *(sorted(refs.glob("*.md")) if refs.is_dir() else [])]


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def read_skills(dirs: list[Path], repo_root: Path) -> tuple[dict[Path, list[tuple[Path, str]]], list[str]]:
    """Each skill's readable files as (path, text), and a finding for each file that is not UTF-8."""
    texts: dict[Path, list[tuple[Path, str]]] = {}
    failures = []
    for d in dirs:
        texts[d] = []
        for f in skill_texts(d):
            try:
                texts[d].append((f, f.read_text(encoding="utf-8")))
            except UnicodeDecodeError as exc:
                failures.append(f"{LABEL} {_rel(f, repo_root)}: not UTF-8 ({exc.reason} at byte "
                                f"{exc.start}) -- the gate cannot read it, so it cannot pass it")
    return texts, failures


def check_monolith(skill_dir: Path, files: list[tuple[Path, str]], repo_root: Path) -> list[str]:
    skill_md = skill_dir / "SKILL.md"
    text = next((t for f, t in files if f == skill_md), None)
    if text is None:
        return []  # unreadable: read_skills already reported it
    words = len(text.split())
    split = any((skill_dir / "references").glob("*.md"))
    if words > MONOLITH_WORD_CAP and not split:
        return [
            f"{LABEL} {_rel(skill_md, repo_root)}: monolith-without-references -- {words} words, "
            f"over the {MONOLITH_WORD_CAP}-word cap, with no references/*.md split. Move a "
            f"self-contained branch into references/ and load it from one line"
        ]
    return []


def paragraphs(text: str) -> list[list[str]]:
    """Each blank-line-separated block as lowercase words, declared reuse removed, short ones dropped."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        normal = " ".join(WORD.findall(block.lower()))
        for marker in DECLARED_MARKERS:
            normal = normal.replace(marker, " ")
        words = normal.split()
        if len(words) >= MIN_PARAGRAPH_WORDS:
            out.append(words)
    return out


def check_duplicates(texts: dict[Path, list[tuple[Path, str]]], repo_root: Path) -> list[str]:
    """Every pair of paragraphs once, including two in the same file. Word level, not
    character level: one swapped word early on shifts every later character, and a
    reworded restatement scored 0.21 by character and 0.79 by word on the fixture that
    set the threshold."""
    entries = [
        (d.name, f, words)
        for d, files in texts.items()
        for f, text in files
        for words in paragraphs(text)
    ]
    failures = []
    for i, (skill_a, file_a, words_a) in enumerate(entries):
        for skill_b, file_b, words_b in entries[i + 1:]:
            ratio = SequenceMatcher(None, words_a, words_b, autojunk=False).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                scope = "within-skill" if skill_a == skill_b else "cross-skill"
                failures.append(
                    f"{LABEL} {_rel(file_a, repo_root)} <-> {_rel(file_b, repo_root)}: "
                    f"duplicate-paragraph ({scope}) -- {ratio:.0%} similar: "
                    f"\"{' '.join(words_a)[:100]}...\". Keep one copy and cite it"
                )
    return failures


SENTENCE_END = re.compile(r"[.!?\n]")


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence (or line) around text[start:end]."""
    left = max((m.end() for m in SENTENCE_END.finditer(text, 0, start)), default=0)
    right = SENTENCE_END.search(text, end)
    return text[left:right.start() if right else len(text)]


def mcp_findings(text: str) -> list[tuple[str, str]]:
    """(rule, note) for each named MCP-call pattern one skill's combined text trips."""
    lower = text.lower()
    found = []
    if SEARCH_TOOL_RE.search(text):
        if "concise" not in lower and "response_format" not in text:
            found.append(("no-concise-mode",
                          "documents an MCP search tool with no concise/response_format mode"))
        if "cursor" not in lower and "paginat" not in lower:
            found.append(("no-pagination",
                          "documents an MCP search tool with no cursor/pagination handling"))
    # A negation clears only the sentence it sits in, never a match elsewhere in the skill.
    loop = next((m for m in PER_FIELD_RE.finditer(text)
                 if not PER_FIELD_NEGATION_RE.search(_sentence(text, m.start(), m.end()))), None)
    if loop:
        found.append(("per-field-search-loop",
                      f"{loop.group(0)!r} reads as one search per field. Search once per record"))
    if FUZZY_SEARCH_RE.search(text) and not (
        "read_resource" in text or DIRECT_LOOKUP_RE.search(text) or "relative path" in lower
    ):
        found.append(("fuzzy-search-only",
                      "documents a fuzzy search tool with no direct-path lookup beside it"))
    if DESTRUCTIVE_RE.search(text) and not DRY_RUN_RE.search(text):
        found.append(("no-dry-run-first",
                      "writes to a live or shared target with no dry-run or copy-first step"))
    if STRATEGY_FLIP_RE.search(text) and "pick one" not in lower:
        found.append(("no-pick-one-rule",
                      "gives two methods for one operation with no rule to finish one first"))
    return found


def check_mcp(skill_dir: Path, files: list[tuple[Path, str]], repo_root: Path) -> list[str]:
    text = "\n".join(t for _, t in files)
    return [f"{LABEL} {_rel(skill_dir, repo_root)}: {rule} -- {note}"
            for rule, note in mcp_findings(text)]


def check_all(repo_root: Path) -> list[str]:
    dirs, failures = skill_dirs(repo_root)
    if not dirs:
        # A gate that scans nothing must not report a pass (GATE-FALSIFIABILITY-1).
        return failures + [f"{LABEL} no skills/<name>/SKILL.md found under {repo_root} -- nothing was checked"]
    texts, unreadable = read_skills(dirs, repo_root)
    failures += unreadable
    for d, files in texts.items():
        failures += check_monolith(d, files, repo_root)
        failures += check_mcp(d, files, repo_root)
    return failures + check_duplicates(texts, repo_root)
