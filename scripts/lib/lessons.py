"""Lesson logs: what went wrong, why, and the rule that now holds, kept as append-only JSONL.

A repo keeps its log under ~/.olivercode/lessons, never in the checkout. The structure log is
~/.olivercode/structure-lessons.jsonl. Each line is one JSON object:

    {"id": "L-1a2b3c4d", "date": "2026-11-19", "scope": "repo", "what": "...", "why": "...", "rule": "...",
     "covered_by": null}

covered_by is null until a check or story covers the lesson, then a reference such as "#513" or
"scripts/hooks/commit_guard.py", and covered_on holds the day it was covered (lesson_cover.verified reads it). Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from lib import failure_log

REQUIRED = ("what", "why", "rule")
SEED_FILE = Path(__file__).resolve().parents[2] / "shared" / "lessons-structure-seed.jsonl"


def path(repo: str | Path | None = None) -> Path:
    """This device's log for one repo, outside every checkout, or the structure log when no repo is given."""
    if repo is None:
        return failure_log.home() / "structure-lessons.jsonl"
    where = Path(repo).resolve()
    digest = hashlib.sha1(str(where).encode("utf-8")).hexdigest()[:12]
    return failure_log.home() / "lessons" / f"{where.name}-{digest}.jsonl"


def read(repo: str | Path | None = None) -> list[dict]:
    p = path(repo)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
    return out


def add(what: str, why: str, rule: str, covered_by: str | None = None, repo: str | Path | None = None) -> dict:
    """Append exactly one line, or raise ValueError naming the missing field."""
    given = {"what": what, "why": why, "rule": rule}
    for key in REQUIRED:
        if not (given[key] or "").strip():
            raise ValueError(f"a lesson needs {key}")
    stamp = f"{date.today().isoformat()}|{what}|{why}|{rule}"
    rec = {"id": "L-" + hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:8], "date": date.today().isoformat(),
           "scope": "structure" if repo is None else "repo", "what": what.strip(), "why": why.strip(),
           "rule": rule.strip(), "covered_by": (covered_by or "").strip() or None}
    p = path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with failure_log.locked(p):  # a cover rewrites the file, so an append waits for it
        failure_log.append_private(p, json.dumps(rec) + "\n")
    return rec


def cover(lesson_id: str, ref: str, repo: str | Path | None = None) -> dict:
    """Set covered_by on one lesson.

    This is the one write that is not an append: it rewrites the whole file through a temp file and a rename, so a
    crash leaves either the old log or the new one, never half of it.
    """
    if not (ref or "").strip():
        raise ValueError("a cover needs a check or story reference")
    p = path(repo)
    with failure_log.locked(p):
        return _cover(p, lesson_id, ref)


def _cover(p: Path, lesson_id: str, ref: str) -> dict:
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    found, out = None, []
    for line in lines:
        try:
            item = json.loads(line) if line.strip() else None
        except ValueError:
            item = None
        if isinstance(item, dict) and item.get("id") == lesson_id:
            item["covered_by"] = ref.strip()
            item["covered_on"] = date.today().isoformat()
            found = item
            line = json.dumps(item)
        out.append(line)
    if found is None:
        raise ValueError(f"no lesson {lesson_id}")
    failure_log.write_private(p, "\n".join(out) + "\n")
    return found



def mark_implemented(ref: str, evidence: str, repo: str | Path | None = None) -> int:
    """Mark lessons linked to REF implemented after the story's completion gate succeeds.

    The lesson remains in the append-only log. The implementation reference and date are
    added to matching records in both the repo and structure logs.
    """
    if not (ref or "").strip() or not (evidence or "").strip():
        raise ValueError("implementation needs a story reference and commit evidence")
    targets = [path(repo)]
    structure = path()
    if structure != targets[0]:
        targets.append(structure)
    changed = 0
    for target in targets:
        with failure_log.locked(target):
            lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
            out, found = [], False
            for line in lines:
                try:
                    item = json.loads(line) if line.strip() else None
                except ValueError:
                    item = None
                if isinstance(item, dict) and item.get("covered_by") == ref and not item.get("implemented_by"):
                    item["implemented_by"] = evidence.strip()
                    item["implemented_on"] = date.today().isoformat()
                    line = json.dumps(item)
                    found = True
                out.append(line)
            if found:
                failure_log.write_private(target, "\n".join(out) + "\n")
                changed += sum(1 for line in lines if line.strip() and _matches_covered(line, ref))
    return changed


def _matches_covered(line: str, ref: str) -> bool:
    try:
        item = json.loads(line)
    except ValueError:
        return False
    return isinstance(item, dict) and item.get("covered_by") == ref

def uncovered(repo: str | Path | None = None) -> list[dict]:
    return [r for r in read(repo) if not r.get("covered_by")]


def seed() -> int:
    """Copy the tracked seed lessons into the structure log, skipping ids already there. Returns how many were added."""
    have = {r.get("id") for r in read()}
    new = [line for line in SEED_FILE.read_text(encoding="utf-8").splitlines()
           if line.strip() and json.loads(line).get("id") not in have]
    if new:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with failure_log.locked(p):
            failure_log.append_private(p, "\n".join(new) + "\n")
    return len(new)
