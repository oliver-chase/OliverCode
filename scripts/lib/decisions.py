"""Import an existing decisions log into decision records.

`olivercode decisions import FILE` reads a markdown log, one entry per `##`/`###` heading (or per top-level bullet when the
file has no headings), and writes one record per entry into the relay log (`relay.records`), with a pointer back to the
file and line. The file itself is never written. A record carries `flag: "reconfirm"` and a `flag_reason` when its entry is
older than 90 days or cites a quantity ("42 GB database") that a later entry gives a different value. The record id comes from
the file path and the entry text, so a second run adds nothing. Standard library only.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from pathlib import Path

from lib import relay

USAGE = """Usage:
  olivercode decisions record --decision ID --thread ID [--words "TEXT"] --option A --option B --choice A [--by NAME]
  olivercode decisions verify ID
  olivercode decisions show [ID]
  olivercode decisions import FILE"""
STALE_DAYS = 90
_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(%|[A-Za-z]{1,12})(?:\s+([A-Za-z][\w-]*))?")
_UNITS = {"kb", "mb", "gb", "tb", "ms", "s", "seconds", "minutes", "hours", "days", "words", "lines", "percent", "%",
          "users", "files", "repos", "builders", "sessions", "requests"}


def parse(text: str) -> list[dict]:
    """The entries of a markdown log: title, body text and the 1-based line each starts on."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if re.match(r"#{2,3}\s+\S", ln)]
    starts = heads or [i for i, ln in enumerate(lines) if re.match(r"[-*]\s+\S", ln)]
    entries = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i:end]).strip()
        title = re.sub(r"^(#{2,3}|[-*])\s+", "", lines[i]).strip()
        entries.append({"title": title, "text": body, "line": i + 1})
    return entries


def entry_date(text: str) -> date | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def quantities(text: str) -> dict[tuple[str, str], str]:
    """Each number with a unit in the text, keyed by its unit and the word after it."""
    found = {}
    for m in _QUANTITY.finditer(_DATE.sub("", text)):
        unit = m.group(2).lower()
        if unit in _UNITS:
            found[(unit, (m.group(3) or "").lower())] = m.group(1)
    return found


def _flag(entry: dict, later: list[dict], today: date) -> str:
    when = entry_date(entry["text"])
    if when and today - when > timedelta(days=STALE_DAYS):
        return f"dated {when.isoformat()}, more than {STALE_DAYS} days ago"
    mine = quantities(entry["text"])
    for other in later:
        for key, value in quantities(other["text"]).items():
            if key in mine and mine[key] != value:
                unit = f"{mine[key]} {key[0]} {key[1]}".strip()
                return f"cites {unit}, which the entry at line {other['line']} gives as {value}"
    return ""


def import_log(source: Path, today: date | None = None) -> tuple[int, int, list[tuple[str, str]]]:
    """Record every entry of SOURCE not yet recorded. Returns (added, already there, [(title, reason)] flagged)."""
    today = today or date.today()
    entries = parse(source.read_text(encoding="utf-8"))
    have = {r.get("decision") for r in relay.records()}
    where = str(source.resolve())
    added, flagged = 0, []
    for n, entry in enumerate(entries):
        digest = hashlib.sha1(f"{where}\n{entry['text']}".encode("utf-8")).hexdigest()[:10]
        reason = _flag(entry, entries[n + 1:], today)
        if reason:
            flagged.append((entry["title"], reason))
        decision = f"import-{digest}"
        if decision in have:
            continue
        extra = {"source": f"{where}:{entry['line']}", "title": entry["title"]}
        if reason:
            extra.update(flag="reconfirm", flag_reason=reason)
        relay.record(entry["text"], decision, ["recorded"], "import", "recorded", "import", extra)
        added += 1
    return added, len(entries) - added, flagged


def _flags(argv: list[str], valued: set[str]):
    """(values by flag, repeated --option list), or None for an unknown flag, a valueless flag or a positional."""
    vals: dict[str, str] = {}
    options: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] not in valued or i + 1 >= len(argv):
            return None
        if argv[i] == "--option":
            options.append(argv[i + 1])
        else:
            vals[argv[i]] = argv[i + 1]
        i += 2
    return vals, options


def _line(rec: dict) -> str:
    return (f"{rec.get('created', '?')}  decision {rec.get('decision', '?')}  thread {rec.get('thread', '?')}  "
            f"choice {rec.get('choice', '?')} of {rec.get('options', '?')}  by {rec.get('by') or '-'}\n"
            f"  words: {rec.get('words', '')}")


def _record(argv: list[str]) -> int:
    parsed = _flags(argv, {"--decision", "--thread", "--words", "--option", "--choice", "--by"})
    if parsed is None or not all(k in parsed[0] for k in ("--decision", "--thread", "--choice")) or not parsed[1]:
        print(USAGE)
        return 1
    vals, options = parsed
    rec = relay.record(vals.get("--words", ""), vals["--decision"], options, vals["--thread"], vals["--choice"], vals.get("--by", ""))
    print(f"Recorded decision {rec['decision']} in {relay.path()}")
    return 0


def _import(argv: list[str]) -> int:
    source = Path(argv[0])
    try:
        added, there, flagged = import_log(source)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"FAIL: cannot read {source}: {exc}")
        return 1
    if added + there == 0:
        print(f"FAIL: {source} has no entries. Start each decision with a ## heading or a top-level bullet.")
        return 1
    print(f"Imported {added} decision record(s) from {source} into {relay.path()}; {there} already recorded. The file is unchanged.")
    for title, reason in flagged:
        print(f"Re-confirm with the owner: {title} ({reason})")
    return 0


def command_decisions(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    if sub == "record":
        return _record(rest)
    if sub == "import" and len(rest) == 1:
        return _import(rest)
    if sub == "verify" and len(rest) == 1:
        try:
            print(_line(relay.verify(rest[0])))
        except ValueError as exc:
            print(f"FAIL: {exc}")
            return 1
        return 0
    if sub == "show" and len(rest) <= 1:
        found = [r for r in relay.records() if not rest or r.get("decision") == rest[0]]
        if not found:
            print("No records.")
            return 1
        print("\n".join(_line(r) for r in found))
        return 0
    print(USAGE)
    return 1
