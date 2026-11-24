"""`olivercode commit-check FILE_OR_TEXT`: run the commit-msg gate on a draft message and print every finding (#881)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.local_config import OC_ROOT

TEMPLATE = OC_ROOT / "core" / "templates" / "project" / "commit-msg"
USAGE = "Usage: olivercode commit-check FILE_OR_TEXT  (the draft message, or the path of a file that holds it)"


def installed_hook() -> Path | None:
    """The commit-msg hook this repo runs on a commit, so the check matches it, or None when it has none."""
    found = subprocess.run(["git", "rev-parse", "--git-path", "hooks/commit-msg"], capture_output=True, text=True)
    path = Path(found.stdout.strip()) if found.returncode == 0 and found.stdout.strip() else None
    return path if path and path.is_file() else None


def command_commit_check(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 1
    draft = " ".join(argv)
    hook = installed_hook() or (TEMPLATE if TEMPLATE.is_file() else None)
    if hook is None:
        subprocess.run([sys.executable, str(OC_ROOT / "scripts" / "build-hooks.py")], capture_output=True)
        hook = TEMPLATE if TEMPLATE.is_file() else None
    if hook is None:
        print("Error: no commit-msg hook found. Run `olivercode sync-hooks` first.")
        return 1
    try:
        given = Path(draft).expanduser()
        is_file = len(argv) == 1 and given.is_file()
    except OSError:  # a one-line message over 255 characters is no file name
        is_file = False
    with tempfile.TemporaryDirectory(prefix="olivercode-commit-check-") as tmp:
        if is_file:
            message = given
        else:
            message = Path(tmp) / "COMMIT_EDITMSG"
            message.write_text(draft.rstrip("\n") + "\n", encoding="utf-8")
        env = {**os.environ, "OLIVERCODE_COMMIT_CHECK": "1", "OLIVERCODE_FAILURE_LOG": os.devnull}  # a draft check is not a refusal
        done = subprocess.run(["bash", str(hook), str(message)], env=env)
    return done.returncode
