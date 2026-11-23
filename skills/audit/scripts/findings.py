#!/usr/bin/env python3
"""The findings ledger of a chunked audit: every chunk writes here, and one coordinator files and reports.

Usage:
    findings.py LEDGER start --target T --coordinator S --chunks a,b,c
    findings.py LEDGER add --chunk C --lens L --priority P1 --where file:line --defect TEXT --evidence TEXT --fix TEXT [--rule KEY]
    findings.py LEDGER add --chunk C --from FILE.json      # a list of objects with the same fields
    findings.py LEDGER done --chunk C
    findings.py LEDGER cross --session S                   # merge duplicates and rules broken in more than one chunk
    findings.py LEDGER file --session S --id F3 --issue 812
    findings.py LEDGER report --session S                  # one Findings table in one priority order
LEDGER is one JSON file for the whole audit, such as <target>/docs/AUDIT-FINDINGS.json. Ids run F1, F2 and so on
across every chunk, and the scale is P0, P1 and P2 from SKILL.md. Only the coordinator named at start runs cross, file
and report, and cross waits until every chunk is done. Exit 1 on a refusal, with the reason.
Tests: python3 -m unittest test_findings
"""
import json
import re
import sys
from pathlib import Path

from check_report import LENSES

SCALE = ("P0", "P1", "P2")
FIELDS = ("lens", "priority", "where", "defect", "evidence", "fix")


class Refused(Exception):
    pass


def load(path):
    p = Path(path)
    if not p.exists():
        raise Refused(f"no ledger at {path}. Fix: run start first")
    return json.loads(p.read_text(encoding="utf-8"))


def save(path, led):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(led, indent=1) + "\n", encoding="utf-8")


def start(path, target, coordinator, chunks):
    if Path(path).exists():
        raise Refused(f"{path} already holds an audit. Fix: every chunk adds to that ledger")
    if not chunks:
        raise Refused("no chunks named. Fix: pass --chunks a,b,c")
    led = {"target": target, "coordinator": coordinator, "scale": list(SCALE), "next": 1,
           "chunks": {c: {"done": False} for c in chunks}, "findings": [], "merged": {}, "cross": False}
    save(path, led)
    return led


def _owner(led, session):
    if session != led["coordinator"]:
        raise Refused(f"session {session!r} is not the coordinator {led['coordinator']!r}. Fix: hand this step to the coordinator")


def add(led, chunk, item):
    if chunk not in led["chunks"]:
        raise Refused(f"unknown chunk {chunk!r}. Fix: use one of {', '.join(led['chunks'])}")
    if led["cross"]:
        raise Refused("the cross-cutting pass already ran. Fix: the coordinator adds late findings to its report")
    missing = [f for f in FIELDS if not str(item.get(f) or "").strip()]
    if missing:
        raise Refused(f"finding lacks {', '.join(missing)}. Fix: give every field in the one schema")
    if item["priority"] not in SCALE:
        raise Refused(f"priority {item['priority']!r} is off the scale. Fix: use P0, P1 or P2")
    lens = item["lens"].strip()
    if lens.lower() not in LENSES:
        raise Refused(f"unknown lens {lens!r}. Fix: use one of {', '.join(LENSES)}")
    where = item["where"] if isinstance(item["where"], list) else [item["where"]]
    fid = f"F{led['next']}"
    led["next"] += 1
    row = {"id": fid, "chunks": [chunk], "lens": lens.lower(), "priority": item["priority"], "where": where,
           "defect": item["defect"].strip(), "evidence": item["evidence"].strip(), "fix": item["fix"].strip(),
           "rule": (item.get("rule") or "").strip(), "issue": None}
    led["findings"].append(row)
    return fid


def done(led, chunk):
    if chunk not in led["chunks"]:
        raise Refused(f"unknown chunk {chunk!r}")
    led["chunks"][chunk]["done"] = True


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _absorb(keep, other, led):
    keep["priority"] = min(keep["priority"], other["priority"])
    keep["chunks"] = sorted(set(keep["chunks"]) | set(other["chunks"]))
    keep["where"] = keep["where"] + [w for w in other["where"] if w not in keep["where"]]
    keep.setdefault("merged_from", []).append(other["id"])
    led["merged"][other["id"]] = keep["id"]


def cross(led, session):
    """Merge duplicates across chunks, then join the breaks of one rule in different chunks into one finding.
    Return (merges, checks): merged ids, and rules seen in one chunk that the coordinator checks in the others."""
    _owner(led, session)
    open_chunks = [c for c, s in led["chunks"].items() if not s["done"]]
    if open_chunks:
        raise Refused(f"chunks still running: {', '.join(open_chunks)}. Fix: wait until each one runs done")
    kept, merges = [], []
    by_key = {}
    for f in led["findings"]:
        keys = [("defect", _norm(f["defect"]))] + [("where", f["lens"], w) for w in f["where"]]
        if f["rule"]:
            keys.append(("rule", _norm(f["rule"])))
        target = next((by_key[k] for k in keys if k in by_key), None)
        if target is None:
            kept.append(f)
            target = f
        else:
            _absorb(target, f, led)
            merges.append((f["id"], target["id"]))
        for k in keys + [("where", target["lens"], w) for w in target["where"]]:
            by_key.setdefault(k, target)
    led["findings"] = kept
    checks = []
    for f in kept:
        others = [c for c in led["chunks"] if c not in f["chunks"]]
        if f["rule"] and others:
            checks.append(f"check rule \"{f['rule']}\" ({f['id']}, found in {', '.join(f['chunks'])}) in {', '.join(others)}")
    led["cross"] = True
    return merges, checks


def file_issue(led, session, fid, issue):
    _owner(led, session)
    if not led["cross"]:
        raise Refused("the cross-cutting pass has not run. Fix: run cross first, so no duplicate is filed")
    fid = led["merged"].get(fid, fid)
    row = next((f for f in led["findings"] if f["id"] == fid), None)
    if row is None:
        raise Refused(f"no finding {fid}")
    number = str(issue).lstrip("#")
    if not number.isdigit() or int(number) == 0:
        raise Refused(f"issue {issue!r} is not an issue number. Fix: pass --issue 812")
    row["issue"] = int(number)
    return fid


def report(led, session):
    """One Findings table in one priority order, every lens named, ready for the report's Findings section."""
    _owner(led, session)
    if not led["cross"]:
        raise Refused("the cross-cutting pass has not run. Fix: run cross first")
    unfiled = [f["id"] for f in led["findings"] if not f["issue"]]
    if unfiled:
        raise Refused(f"findings with no issue: {', '.join(unfiled)}. Fix: file each one")
    order = sorted(led["findings"], key=lambda f: (f["priority"], int(f["id"][1:])))
    lines = ["| Lens | Priority | Id | Where | Defect | Evidence | Fix | Issue |", "|---|---|---|---|---|---|---|---|"]
    for f in order:
        cell = lambda s: s.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {f['lens'].capitalize()} | {f['priority']} | {f['id']} | {cell(', '.join(f['where']))} | "
                     f"{cell(f['defect'])} | {cell(f['evidence'])} | {cell(f['fix'])} | #{f['issue']} |")
    seen = {f["lens"] for f in order}
    lines += [f"| {lens.capitalize()} | Checked, nothing found across every chunk | | | | | | |" for lens in LENSES if lens not in seen]
    return "\n".join(lines)


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip())
        return 2
    path, cmd, rest = argv[1], argv[2], argv[3:]
    opts = {rest[i][2:]: rest[i + 1] for i in range(0, len(rest) - 1, 2) if rest[i].startswith("--")}
    try:
        if cmd == "start":
            start(path, opts.get("target", ""), opts.get("coordinator", ""), [c for c in opts.get("chunks", "").split(",") if c])
            print(f"ledger started at {path}")
            return 0
        led = load(path)
        if cmd == "add":
            items = json.loads(Path(opts["from"]).read_text(encoding="utf-8")) if "from" in opts else [opts]
            ids = [add(led, opts.get("chunk", ""), item) for item in items]
            print(" ".join(ids))
        elif cmd == "done":
            done(led, opts.get("chunk", ""))
            print(f"chunk {opts.get('chunk')} done")
        elif cmd == "cross":
            merges, checks = cross(led, opts.get("session", ""))
            for old, new in merges:
                print(f"merged {old} into {new}")
            for c in checks:
                print(c)
            print(f"cross pass: {len(merges)} merged, {len(led['findings'])} findings, {len(checks)} rule check(s)")
        elif cmd == "file":
            print(f"{file_issue(led, opts.get('session', ''), opts.get('id', ''), opts.get('issue', '0'))} filed as #{str(opts.get('issue')).lstrip('#')}")
        elif cmd == "report":
            print(report(led, opts.get("session", "")))
            return 0
        else:
            print(__doc__.strip())
            return 2
        save(path, led)
        return 0
    except Refused as e:
        print(f"REFUSED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
