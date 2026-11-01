"""OliverCode's hook entries in Claude Code's user settings, merged in without touching anything else.

`~/.claude/settings.json` belongs to the operator: permissions, theme, model and any hook
they wrote. OliverCode adds only the entries in MANAGED, recognised by the hook script's
file name under a `scripts/hooks/` folder, so a re-install replaces its own entries (also
after the checkout moves) and never edits or duplicates the operator's.

The hooks point at the scripts in this checkout, so an edit here takes effect in the next
session with no reinstall.
"""

from __future__ import annotations

import json
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
# (event, matcher or None, script). Stop takes no matcher.
MANAGED = (
    ("SessionStart", "startup", "session_check.py"),
    ("PreToolUse", "Bash", "commit_guard.py"),
    ("Stop", None, "early-stop-guard.py"),
)
TIMEOUT_S = 10


def _command(script: str, hooks_dir: Path) -> str:
    return f'python3 "{hooks_dir / script}"'


def _is_managed(handler: dict) -> bool:
    cmd = handler.get("command", "") if isinstance(handler, dict) else ""
    return "/scripts/hooks/" in cmd and any(script in cmd for _, _, script in MANAGED)


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


def merge(settings: dict, hooks_dir: Path = HOOKS_DIR) -> dict:
    """Return settings with OliverCode's hooks current and every other key and hook unchanged.
    Raises ValueError for a settings shape it cannot merge into."""
    _check_shape(settings)
    out = json.loads(json.dumps(settings))  # deep copy; the caller's dict stays as read
    hooks = out.setdefault("hooks", {})
    for event in dict.fromkeys([e for e, _, _ in MANAGED] + list(hooks)):  # a fixed order, so a re-install never churns the file
        groups = []
        for group in hooks.get(event, []):
            kept = [h for h in group.get("hooks", []) if not _is_managed(h)]
            if kept:
                groups.append({**group, "hooks": kept})
        hooks[event] = groups
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
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_name(settings_path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    tmp.replace(settings_path)  # one rename, so a crash never leaves half a settings file
    return "updated" if current.get("hooks") else "added"
