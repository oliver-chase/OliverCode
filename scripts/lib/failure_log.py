"""The local failure log that the commit hooks write, and the gate-block report built on it.

One line per blocked commit or audit finding: time, repo, gate, reason, tab separated. The file sits in
~/.olivercode (OLIVERCODE_HOME overrides it), outside every repo, so no commit can carry it.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def home() -> Path:
    """The OliverCode home. It holds the owner's words and repo names, so only its user can read it:
    the folder is made mode 700 and every file in it is tightened to 600."""
    path = Path(os.environ.get("OLIVERCODE_HOME") or Path.home() / ".olivercode")
    try:
        if not path.is_dir() or (path.stat().st_mode & 0o777) != 0o700:  # a folder already private was walked on an earlier call
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            privatize(path)
    except OSError:
        pass
    return path


def write_atomic(path: Path, text: str) -> None:
    """Write through a temporary file and a rename, so two writers never leave a half file. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def privatize(path: Path) -> None:
    """Set a folder to mode 700 and every file and folder under it to 600 and 700."""
    os.chmod(path, 0o700)
    for entry in os.scandir(path):
        if entry.is_symlink():
            continue
        if entry.is_dir():
            privatize(Path(entry.path))
        elif (entry.stat().st_mode & 0o777) != 0o600:
            os.chmod(entry.path, 0o600)


def log_path() -> Path:
    return Path(os.environ.get("OLIVERCODE_FAILURE_LOG") or home() / "failures.log")


def append_private(path: Path, text: str) -> None:
    """Append text to a file that only the owner can read, creating it at mode 600."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def record(gate: str, reason: str, repo: str = "") -> None:
    """Append one finding, the way the hooks do."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clean = " ".join(reason.split())[:200]
    append_private(path, f"{when}\t{repo or Path.cwd().name}\t{gate}\t{clean}\n")
    trim(path)


# A log keeps its newest lines, so it never grows past a fixed size however long the machine runs.
KEEP_LINES = 1000


def trim(path: Path, keep: int = KEEP_LINES) -> None:
    """Cut a log to its newest `keep` lines once it holds twice that, so most appends cost no rewrite."""
    try:
        if path.stat().st_size < 2 * keep * 8:  # a line is never under 8 bytes, so a smaller file cannot hold twice `keep`
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return
    if len(lines) > 2 * keep:
        write_atomic(path, "".join(lines[-keep:]))


def entries() -> list[tuple[str, str, str, str]]:
    path = log_path()
    if not path.is_file():
        return []
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    return [tuple(r) for r in rows if len(r) == 4]


REPEAT = 3


def repeated(minimum: int = REPEAT) -> dict[tuple[str, str], list[str]]:
    """(gate, reason) -> times, for each blocker the log holds `minimum` or more times. No model call; maintain findings are left out."""
    seen: dict[tuple[str, str], list[str]] = {}
    for when, _repo, gate, reason in entries():
        if gate != "maintain":
            seen.setdefault((gate, reason), []).append(when)
    return {k: v for k, v in seen.items() if len(v) >= minimum}
