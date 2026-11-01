"""Cross-doc content duplication check. GATE-DUPLICATION-1 in docs/DECISIONS.md.

Slides a 15-word window across every tracked markdown file; a window shared by two
files fails the build unless it matches a declared canonical-reuse marker below.
Substring match, not semantic similarity, by design -- see the ledger entry for why.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

WINDOW = 15  # words; below this, ordinary short phrase overlap is expected and noisy

WORD = re.compile(r"[A-Za-z0-9']+")

# Fenced code blocks are not excluded: a short shared command (a few words) is already
# below WINDOW, and a long duplicated snippet (a whole probe script, a whole gate list)
# is exactly the kind of copy-paste drift this check exists to catch -- excluding code
# fences would blind it to the B15 finding that motivated building it.

# Snippets that are deliberate reuse, not drift -- matched as a normalized (lowercase,
# punctuation-stripped) substring of the finding, so one entry covers every file pair
# that shares it instead of listing pairs combinatorially. Adding an entry here without
# a real reason recreates the exact blind spot hook_drift_check.py's
# DECLARED_DIFFERENCES pattern exists to close.
DECLARED_MARKERS: dict[str, str] = {
    "repo profiles json gitignored real fleet or shared repo profiles example "
    "json tracked": (
        "The canonical parenthetical naming where per-repo config lives. Reused as a "
        "fixed term across every doc that mentions repo profiles, the way a glossary "
        "term is reused -- not an independently-authored fact that could drift, "
        "because there is only one real file path being named."
    ),
    "dirname readlink claude claude md": (
        "The $OC-resolution snippet (docs/ADOPTING.md, CLAUDE.md, "
        "skills/olivercode-adoption/SKILL.md). Deliberately identical everywhere it "
        "appears -- ADOPTING.md itself calls this 'the one hard constraint' and every "
        "doc teaching it should show the exact same pattern so it is recognizable."
    ),
    "optimize do not amputate you are pointing existing rules at a shared home not "
    "deleting them": (
        "docs/ADOPTING.md's governing rule, restated identically in "
        "skills/olivercode-adoption/SKILL.md because the skill exists to drive that "
        "exact rule during a live session -- see the skill's own 'the rule that "
        "governs everything here' section."
    ),
    "in sessions whose working directory is almost never olivercode so every path in "
    "it must resolve from anywhere": (
        "Same $OC-constraint explanation, ADOPTING.md and its own driving skill. "
        "Declared alongside the $OC-resolution snippet above for the same reason."
    ),
    "scripts qa probe secret gate sh writes a fake secret commits expects a block": (
        "The one canonical invocation line for scripts/qa/probe-secret-gate.sh "
        "(docs/ADOPTING.md, docs/NEW-MACHINE.md, skills/olivercode-adoption/SKILL.md) "
        "-- a runnable example DOCUMENTATION-STANDARD.md wants shown identically "
        "everywhere it appears, not three independently-worded ones."
    ),
}


def _declared(snippet: str) -> bool:
    return any(marker in snippet for marker in DECLARED_MARKERS)


def _tracked_md(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def _windows(words: list[str]) -> dict[tuple[str, ...], int]:
    """Map each WINDOW-word tuple to its earliest start index in this file."""
    result: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - WINDOW + 1):
        w = tuple(words[i : i + WINDOW])
        if w not in result:
            result[w] = i
    return result


def _merge_spans(indices: list[int]) -> list[tuple[int, int]]:
    """Collapse overlapping/adjacent window-start indices into (start, end) spans."""
    if not indices:
        return []
    indices = sorted(set(indices))
    spans = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i <= prev + WINDOW:  # overlapping or touching
            prev = i
            continue
        spans.append((start, prev + WINDOW))
        start = prev = i
    spans.append((start, prev + WINDOW))
    return spans


def check_all(repo_root: Path) -> list[str]:
    failures: list[str] = []

    files = _tracked_md(repo_root)
    # file -> word list, file -> window-hash -> earliest start index
    file_words: dict[str, list[str]] = {}
    file_windows: dict[str, dict[tuple[str, ...], int]] = {}
    for rel in files:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        words = WORD.findall(text.lower())
        file_words[rel] = words
        file_windows[rel] = _windows(words)

    # window -> {file: start_index}, only for windows seen in 2+ files
    window_hits: dict[tuple[str, ...], dict[str, int]] = {}
    for rel, windows in file_windows.items():
        for w, idx in windows.items():
            window_hits.setdefault(w, {})[rel] = idx

    # file-pair -> {file: [start indices of shared windows]}
    pair_starts: dict[frozenset[str], dict[str, list[int]]] = {}
    for w, hits in window_hits.items():
        if len(hits) < 2:
            continue
        rels = sorted(hits)
        for i, a in enumerate(rels):
            for b in rels[i + 1 :]:
                key = frozenset({a, b})
                pair_starts.setdefault(key, {}).setdefault(a, []).append(hits[a])
                pair_starts.setdefault(key, {}).setdefault(b, []).append(hits[b])

    for pair, starts_by_file in sorted(pair_starts.items(), key=lambda kv: sorted(kv[0])):
        a, b = sorted(pair)
        spans_a = _merge_spans(starts_by_file.get(a, []))
        for start, end in spans_a:
            snippet = " ".join(file_words[a][start:end])
            if _declared(snippet):
                continue
            display = snippet if len(snippet) <= 160 else snippet[:157] + "..."
            failures.append(
                f"duplication: {a} <-> {b}: shared passage ({end - start} words): \"{display}\""
            )

    return failures
