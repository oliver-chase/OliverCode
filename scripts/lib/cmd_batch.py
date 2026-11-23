"""Launcher command `batch`: a batch of content stops after one sample until the owner approves it (#628).

Rejections used to arrive after a whole batch was built. `olivercode batch start NAME --count N` records the batch in
`~/.olivercode/batches.json` as waiting for its sample. `batch next NAME` exits 0 while the batch is approved or has a
single item, and exits 1 with the sample step once a second item is asked for before `batch approve NAME`. The sample
and its approval are the owner's, whose exact words `olivercode decisions record` keeps.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib import failure_log

USAGE = """Usage:
  olivercode batch start NAME --count N
  olivercode batch next NAME
  olivercode batch approve NAME"""


def path() -> Path:
    return failure_log.home() / "batches.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def start(name: str, count: int) -> None:
    data = load()
    data[name] = {"count": count, "built": 0, "approved": False}
    save(data)


def approve(name: str) -> bool:
    data = load()
    if name not in data:
        return False
    data[name]["approved"] = True
    save(data)
    return True


def next_item(name: str) -> tuple[bool, str]:
    """(allowed, reason). The first item is the sample, and every later one waits for approval."""
    data = load()
    batch = data.get(name)
    if batch is None:
        return False, f"no batch named {name}; run `olivercode batch start {name} --count N` first"
    if batch["built"] >= 1 and not batch["approved"]:
        return False, (f"the sample for {name} is built and not approved. Show it to the owner and run "
                       f"`olivercode batch approve {name}` with the owner's yes before the other {batch['count'] - batch['built']} item(s)")
    batch["built"] += 1
    save(data)
    return True, f"item {batch['built']} of {batch['count']} may be built"


def command_batch(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    if sub == "start" and len(rest) == 3 and rest[1] == "--count" and rest[2].isdigit() and int(rest[2]) > 0:
        start(rest[0], int(rest[2]))
        print(f"Batch {rest[0]} recorded: {rest[2]} item(s), the first is the sample.")
        return 0
    if sub == "next" and len(rest) == 1:
        ok, why = next_item(rest[0])
        print(why)
        return 0 if ok else 1
    if sub == "approve" and len(rest) == 1:
        if approve(rest[0]):
            print(f"Batch {rest[0]} approved.")
            return 0
        print(f"No batch named {rest[0]}.")
        return 1
    print(USAGE)
    return 1
