"""Versioned moves of the user's state files, run by `olivercode install` and so by every update.

When a release changes where a state file lives, it adds one Migration here with the next number. Install runs each
migration this machine has not run yet, exactly once: it copies the old file to ~/.olivercode/backups first, writes
its content into the new home (a JSONL log is appended without repeating a line, a JSON file keeps every value the
new home already holds), then removes the old file, so two copies never remain. The numbers that ran are kept in
~/.olivercode/migrations.json (OLIVERCODE_HOME overrides the folder).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lib import failure_log


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    source: Callable[[Path], Path]  # the old file, given the OliverCode checkout
    target: Callable[[Path], Path]  # where it lives now
    kind: str  # "jsonl" appends lines, "json" merges keys


MIGRATIONS: tuple[Migration, ...] = (
)


def record_file() -> Path:
    return failure_log.home() / "migrations.json"


def applied() -> dict:
    """{number as text: the day it ran}."""
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("applied", {}) if isinstance(data, dict) else {}


def _mark(number: int) -> None:
    done = applied()
    done[str(number)] = time.strftime("%Y-%m-%d")
    path = record_file()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"applied": done}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _merge(kind: str, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
        return
    if kind == "jsonl":
        have = target.read_text(encoding="utf-8")
        seen = set(have.splitlines())
        new = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip() and line not in seen]
        if new:
            target.write_text(have + ("" if not have or have.endswith("\n") else "\n") + "\n".join(new) + "\n", encoding="utf-8")
        return
    old, current = json.loads(source.read_text(encoding="utf-8")), json.loads(target.read_text(encoding="utf-8"))
    target.write_text(json.dumps({**old, **current}, indent=2) + "\n", encoding="utf-8")


def run(oc_root: Path, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[str]:
    """Run every migration not yet recorded; return one line per file moved."""
    done, moved = applied(), []
    for m in sorted(migrations, key=lambda m: m.number):
        if str(m.number) in done:
            continue
        source, target = m.source(oc_root), m.target(oc_root)
        if source.is_file():
            backups = failure_log.home() / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / f"migration-{m.number}-{source.name}.{time.strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(source, backup)
            _merge(m.kind, source, target)
            source.unlink()
            moved.append(f"{m.name}: {source} moved to {target} (backup {backup})")
        _mark(m.number)
    return moved
