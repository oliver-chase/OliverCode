"""Launcher command `limits`: `olivercode limits check [--root DIR]` prints the tracked line count against the ceiling in docs/LIMITS.json (#879, #882).

It warns when the count is over and exits 0 always, so size never blocks a commit or a land. Rules are in lib/limits.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lib import limits

USAGE = "Usage: olivercode limits check [--root DIR]"


def command_limits(argv: list[str]) -> int:
    if argv[:1] != ["check"] or len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--root"):
        print(USAGE)
        return 1
    top = subprocess.run(["git", "-C", argv[2] if len(argv) == 3 else ".", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        print("limits runs inside a git repository.")
        return 1
    print("\n".join(limits.check(Path(top.stdout.strip()))))
    return 0
