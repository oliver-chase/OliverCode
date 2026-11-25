"""Launcher command `lesson`: add, list, cover and seed the lesson logs."""

from __future__ import annotations

from lib import lesson_cover, lesson_flags, lessons
from lib.cli import flags as _flags
from lib.local_config import OC_ROOT

USAGE = """Usage:
  olivercode lesson add [--structure | --repo DIR] --what TEXT --why TEXT --rule TEXT [--covered-by REF]
  olivercode lesson list [--structure | --repo DIR] [--uncovered]
  olivercode lesson cover ID REF [--structure | --repo DIR]
  olivercode lesson seed"""


def _story_state(number: int) -> str:
    return lesson_flags.story_state(number)


def _target(vals: dict, seen: set):
    """(repo, ok): repo is None for the structure log, and the default is the current folder."""
    if "--structure" in seen and "--repo" in vals:
        return None, False
    return (None if "--structure" in seen else vals.get("--repo", ".")), True


def _line(r: dict) -> str:
    ref = r.get("covered_by")
    tracking = f"tracked by {ref}" if ref else "not tracked"
    implementation = (f"implemented by {r['implemented_by']} on {r['implemented_on']}"
                      if r.get("implemented_by") and r.get("implemented_on") else "implementation pending")
    mark = ", verified" if lesson_cover.verified(r) else ""
    return (f"{r.get('id', '?')}  {r.get('date', '?')}  {tracking}; {implementation}{mark}\n"
            f"  what: {r.get('what', '')}\n  why: {r.get('why', '')}\n  rule: {r.get('rule', '')}")


def command_lesson(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    valued = {"--repo", "--what", "--why", "--rule", "--covered-by"}
    parsed = _flags(rest, valued, {"--structure", "--uncovered"})
    if parsed is None or sub not in ("add", "list", "cover", "seed"):
        print(USAGE)
        return 1
    vals, _, pos, seen = parsed
    repo, ok = _target(vals, seen)
    if not ok:
        print(USAGE)
        return 1
    try:
        if sub == "add" and not pos:
            rec = lessons.add(vals.get("--what", ""), vals.get("--why", ""), vals.get("--rule", ""),
                              vals.get("--covered-by"), repo)
            print(f"Recorded lesson {rec['id']} in {lessons.path(repo)}")
            return 0
        if sub == "list" and not pos:
            found = lessons.uncovered(repo) if "--uncovered" in seen else lessons.read(repo)
            print("\n".join(_line(r) for r in found) if found else "No lessons.")
            return 0
        if sub == "cover" and len(pos) == 2:
            why = lesson_flags.check_ref(pos[1], repo if repo is not None else OC_ROOT, state=_story_state)
            if why:
                print(f"FAIL: {why}")
                return 1
            rec = lessons.cover(pos[0], pos[1], repo)
            print(f"Lesson {rec['id']} is covered by {rec['covered_by']}")
            return 0
        if sub == "seed" and not pos and not vals and not seen:
            print(f"Added {lessons.seed()} seed lessons to {lessons.path()}")
            return 0
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(USAGE)
    return 1
