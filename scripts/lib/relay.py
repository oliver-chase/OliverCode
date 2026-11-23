"""The decision ledger: one decision, kept as an audit trail.

~/.olivercode/relays.jsonl (OLIVERCODE_HOME overrides the folder) holds one JSON line per recorded decision:

    {"created": "2026-11-19T10:00:00+00:00", "decision": "513", "thread": "T1", "words": "Option A",
     "options": ["A", "B"], "choice": "A", "by": "SID"}

`verify` proves a record is complete. Nothing in this module unlocks an action: a session reads a verified record, where
`words` holds the owner's exact words. Standard library only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log

REQUIRED = (("decision", "the decision id"),
            ("options", "the options"), ("thread", "the thread id"), ("choice", "the choice"))


def path() -> Path:
    return failure_log.home() / "relays.jsonl"


def record(words: str, decision_id: str, options: list[str], thread_id: str, choice: str, by: str = "",
           extra: dict | None = None) -> dict:
    """Append one line for the decision and return it. EXTRA adds fields such as an import's source and flag."""
    rec = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "decision": decision_id,
           "thread": thread_id, "words": words, "options": list(options), "choice": choice, "by": by, **(extra or {})}
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def records() -> list[dict]:
    p = path()
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


def check(rec: dict) -> dict:
    """The record itself, or ValueError naming the first missing field or a choice outside the options."""
    for key, label in REQUIRED:
        value = rec.get(key)
        if not value or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"The record is missing {label}")
    options = rec["options"]
    if not isinstance(options, list) or not all(isinstance(o, str) and o for o in options):
        raise ValueError("The record's options are not a list of names")
    if rec["choice"] not in options:
        raise ValueError(f"The choice {rec['choice']!r} is not one of the options {options}")
    return rec


def verify(decision_id: str) -> dict:
    """The newest record for the decision, checked. Raises ValueError for no record or an incomplete one."""
    found = [r for r in records() if r.get("decision", "") == decision_id]
    if not found:
        raise ValueError(f"No record for decision {decision_id!r}")
    return check(found[-1])
