"""When each Claude Code hook last fired, so `olivercode cutlist` can name a hook that never does (#675).

A hook runs the script's main through `run`. The hook is recorded as `ran` on every run and as `acted` when its output
blocks, denies, warns or adds context. One small file per hook under ~/.olivercode/hook-fires (OLIVERCODE_HOME overrides the
folder) holds the last time of each, and a write happens only when the stored day differs, so a busy hook costs one write a
day. Standard library only, and a logging failure never changes what the hook does.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone

try:
    from lib.failure_log import home, write_atomic
except ImportError:  # loaded bare, with scripts/lib on the path
    from failure_log import home, write_atomic

FOLDER = "hook-fires"


def acted(output: str) -> bool:
    """True when a hook's output changes what the session sees or does. An allow decision and an empty object do not."""
    try:
        data = json.loads(output)
    except ValueError:
        return bool(output.strip())
    if not isinstance(data, dict):
        return False
    inner = data.get("hookSpecificOutput") or {}
    if not isinstance(inner, dict):
        inner = {}
    return bool(data.get("decision") == "block" or data.get("systemMessage") or inner.get("additionalContext")
                or inner.get("permissionDecision") in {"deny", "ask"})


def record(name: str, did_act: bool) -> None:
    """Note a run, and an action when `did_act`. Never raises."""
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = home() / FOLDER / f"{name}.json"
        try:
            last = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = {}
        if not isinstance(last, dict):
            last = {}
        new = dict(last)
        new.setdefault("since", now)
        for key, on in (("ran", True), ("acted", did_act)):
            if on and str(last.get(key, ""))[:10] != now[:10]:
                new[key] = now
        if new != last:
            write_atomic(path, json.dumps(new) + "\n")
    except (OSError, TypeError):
        pass


def last_fires() -> dict[str, dict[str, str]]:
    """hook name -> {"since": first run, "ran": time, "acted": time}, from the files `record` wrote."""
    out: dict[str, dict[str, str]] = {}
    folder = home() / FOLDER
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[path.stem] = {k: str(v) for k, v in data.items() if k in {"ran", "acted", "since"}}
    return out


def run(name: str, main) -> int:
    """Run a hook's main, pass its output through unchanged and record the run. An exception keeps its output and propagates."""
    real, buffer = sys.stdout, io.StringIO()
    sys.stdout = buffer
    try:
        code = main()
    finally:
        sys.stdout = real
        real.write(buffer.getvalue())
        real.flush()
    record(name, acted(buffer.getvalue()))
    return code
