"""OliverCode's hook entries in Claude Code's user settings, merged in without touching anything else.

`~/.claude/settings.json` belongs to the operator: permissions, theme, model and any hook
they wrote. OliverCode adds only the entries in MANAGED, recognised by the exact command
`_command()` writes for one of its scripts under any checkout's `scripts/hooks/` folder, so a
re-install replaces its own entries (also after the checkout moves) and never edits,
duplicates or removes the operator's, even one that runs a script of the same name. `remove` takes
out exactly those entries by the same rule, for `olivercode uninstall`.

The hooks point at the scripts in this checkout, so an edit here takes effect in the next
session with no reinstall.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
# (event, matcher or None, script). Stop takes no matcher.
MANAGED = (
    ("SessionStart", "startup", "session_check.py"),
    ("PreToolUse", "Bash|Edit|Write|MultiEdit", "pretool_guard.py"),
    ("PostToolUse", "Bash", "gh_watch.py"),
    ("Stop", None, "early-stop-guard.py"),
)
# Entries an earlier install wrote, one per guard. They are still recognised, so a re-install or an
# uninstall takes them out, and the one pretool_guard.py entry replaces all four.
LEGACY = ("commit_guard.py", "placement_guard.py", "policy_guard.py", "gh_guard.py")
TIMEOUT_S = 10


def _command(script: str, hooks_dir: Path) -> str:
    return f'python3 "{hooks_dir / script}"'


# The exact form _command() writes, from any checkout path. It is the only form install has
# ever written, so nothing looser is needed to recognise an older install.
_MANAGED_COMMAND = re.compile(
    r'python3 "(.+)/scripts/hooks/(' + "|".join(re.escape(s) for s in [m[2] for m in MANAGED] + list(LEGACY)) + r')"')


def _is_managed(handler: dict) -> bool:
    cmd = handler.get("command", "") if isinstance(handler, dict) else ""
    return isinstance(cmd, str) and _MANAGED_COMMAND.fullmatch(cmd) is not None


def _check_shape(settings) -> None:
    """Refuse a settings file this merge could only rewrite by guessing what the owner meant."""
    if not isinstance(settings, dict):
        raise ValueError("the file is not a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    for event, groups in hooks.items():
        if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks", []), list) for g in groups):
            raise ValueError(f'"hooks.{event}" is not a list of hook groups')


def _strip_managed(hooks: dict) -> dict:
    """Each event's hook groups with OliverCode's handlers taken out. A group left with no
    handler is dropped, and an event left with no group maps to an empty list."""
    out = {}
    for event, groups in hooks.items():
        out[event] = []
        for group in groups:
            kept = [h for h in group.get("hooks", []) if not _is_managed(h)]
            if kept:
                out[event].append({**group, "hooks": kept})
    return out


def _write(settings_path: Path, settings: dict) -> None:
    # Write through a symlinked settings.json to its target, so the link survives, and
    # keep the file's mode, so a private 0600 file stays private.
    target = settings_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    if target.exists():
        os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
    tmp.replace(target)  # one rename, so a crash never leaves half a settings file


def merge(settings: dict, hooks_dir: Path = HOOKS_DIR) -> dict:
    """Return settings with OliverCode's hooks current and every other key and hook unchanged.
    Raises ValueError for a settings shape it cannot merge into."""
    _check_shape(settings)
    out = json.loads(json.dumps(settings))  # deep copy; the caller's dict stays as read
    hooks = out.setdefault("hooks", {})
    # A fixed event order, so a re-install never churns the file.
    hooks.update(_strip_managed({e: hooks.get(e, []) for e in dict.fromkeys([e for e, _, _ in MANAGED] + list(hooks))}))
    for event, matcher, script in MANAGED:
        group = {"hooks": [{"type": "command", "command": _command(script, hooks_dir), "timeout": TIMEOUT_S}]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks[event].append(group)
    out["hooks"] = {e: g for e, g in hooks.items() if g}
    return out


def missing(settings_path: Path, hooks_dir: Path = HOOKS_DIR) -> list[str]:
    """The managed hook scripts this checkout's install would add and the settings lack."""
    try:
        current = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
        _check_shape(current)
    except (OSError, ValueError):
        current = {}
    present = {h.get("command") for groups in (current.get("hooks") or {}).values()
               for g in groups for h in g.get("hooks", []) if isinstance(h, dict)}
    return [script for _, _, script in MANAGED if _command(script, hooks_dir) not in present]


def install(settings_path: Path, hooks_dir: Path = HOOKS_DIR) -> str:
    """Write the merged settings. Returns "added", "updated" or "already".
    Raises ValueError, leaving the file untouched, when it is not JSON or has a shape the merge refuses."""
    current = {}
    if settings_path.is_file():
        text = settings_path.read_text()
        current = json.loads(text) if text.strip() else {}
    merged = merge(current, hooks_dir)
    if merged == current:
        return "already"
    _write(settings_path, merged)
    return "updated" if current.get("hooks") else "added"


def without(settings: dict) -> dict:
    """Return settings with every OliverCode hook entry taken out and everything else as it was.
    An event, or the "hooks" key itself, that only OliverCode's entries filled is dropped.
    Raises ValueError for a settings shape it cannot read safely."""
    _check_shape(settings)
    out = json.loads(json.dumps(settings))
    if "hooks" not in out:
        return out
    stripped = _strip_managed(out["hooks"])
    if stripped == out["hooks"]:
        return out  # nothing of OliverCode's here, so the owner's layout stays byte for byte
    out["hooks"] = {e: g for e, g in stripped.items() if g}
    if not out["hooks"]:
        del out["hooks"]
    return out


def remove(settings_path: Path) -> str:
    """Take OliverCode's hook entries out of the settings file. Returns "removed", "deleted"
    or "absent". When nothing but OliverCode's entries was in a plain file, the file itself
    goes, since Claude Code reads an absent settings file and `{}` the same way.
    Raises ValueError, leaving the file untouched, when it is not JSON or has a shape it refuses."""
    if not settings_path.is_file():
        return "absent"
    text = settings_path.read_text()
    current = json.loads(text) if text.strip() else {}
    cleaned = without(current)
    if cleaned == current:
        return "absent"
    if not cleaned and not settings_path.is_symlink():  # a linked file is the owner's to keep
        settings_path.unlink()
        return "deleted"
    _write(settings_path, cleaned)
    return "removed"
