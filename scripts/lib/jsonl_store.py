"""One JSONL list store (#1207), shared by candidates.py and story_outbox.py so a locking or write fix is made once.

One JSON object per line. A row is kept only when it is a dict with a repo and a title, the shape both lists hold.
`locked` guards a read-modify-write with an exclusive flock on a sibling .lock file, named by swapping the suffix
(candidates.jsonl -> candidates.lock), matching the names each file already used before this module existed.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path


def read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("repo") and item.get("title"):
            out.append(item)
    return out


def save(path: Path, rows: list[dict]) -> None:
    """Replace the file with one line per row, or remove it when `rows` is empty. Atomic: a reader sees the old file or the new one."""
    if not rows:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


@contextmanager
def locked(path: Path):
    """One writer at a time, so a rewrite never drops an add made while it ran."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
