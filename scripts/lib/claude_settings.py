"""OliverCode's hook entries in Claude Code's user settings, merged in without touching anything else.

`~/.claude/settings.json` belongs to the operator: permissions, theme, model and any hook
they wrote. OliverCode adds only the entries in MANAGED, recognised by the exact command
`_command()` writes for one of its scripts under any checkout's `scripts/hooks/` folder, so a
re-install replaces its own entries (also after the checkout moves) and never edits,
duplicates or removes the operator's, even one that runs a script of the same name. `remove` takes
out exactly those entries by the same rule, for `olivercode uninstall`.

Install also drops an entry in that exact form whose script is missing from this checkout's
`scripts/hooks/`, so a hook cut from the repo never leaves a dead entry behind.

The hooks point at the scripts in this checkout, so an edit here takes effect in the next
session with no reinstall.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

OC_ROOT = Path(__file__).resolve().parent.parent.parent  # the checkout this file ships in

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
# (event, matcher or None, script). Stop and UserPromptSubmit take no matcher.
MANAGED = (
    ("SessionStart", "startup", "session_check.py"),
    ("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit|Agent|Task", "pretool_guard.py"),
    ("PostToolUse", "Bash", "gh_watch.py"),
    ("Stop", None, "early-stop-guard.py"),
    ("Stop", None, "wip_save.py"),
    ("UserPromptSubmit", None, "lesson_capture.py"),
    ("UserPromptSubmit", None, "owner_decision_capture.py"),
    ("UserPromptSubmit", None, "error_paste.py"),
    ("UserPromptSubmit", None, "status_hint.py"),
)
# Scripts cut from the repo. Install and update remove an entry that runs one, from any checkout, so a machine that
# installed an older version never keeps a hook for a script that is about to go (#886).
RETIRED = ("start_guard.py", "start_confirm.py", "ask_guard.py", "owner_prompt.py", "context_guard.py", "denial_watch.py")
TIMEOUT_S = 10
# Tools a session needs without a permission prompt: session control, the sidebar, worktree cleanup and the repo's
# own validation. Install adds them to permissions.allow beside the owner's entries and health reports any missing.
ALLOW = (
    "mcp__ccd_session__start_session",
    "mcp__ccd_session__dismiss_task",
    "mcp__ccd_session_mgmt__stop_session",
    "mcp__ccd_session_mgmt__send_message",
    "mcp__ccd_session_mgmt__set_session_title",
    "mcp__ccd_session_mgmt__archive_session",
    "mcp__ccd_session_mgmt__detach_session",
    "mcp__ccd_sidebar__set_pinned",
    "mcp__ccd_sidebar__move_sessions",
    "SendMessage",
    "Bash(olivercode clean*)",
    "Bash(git worktree prune*)",
)

# Entries an older install wrote that a later one no longer pre-approves: `worktree remove *` matches --force, and
# `validate.sh*` runs whatever script the repo in front of the session ships. Install takes them back out.
RETIRED_ALLOW = ("Bash(git worktree remove *)", "Bash(git -C * worktree remove *)", "Bash(bash scripts/validate.sh*)")

# One line per ALLOW entry on what it permits, shown by `olivercode install --show-allow` before install writes them.
ALLOW_WHY = {
    "mcp__ccd_session__start_session": "start a new Claude Code session, for a builder on a backlog story",
    "mcp__ccd_session__dismiss_task": "withdraw a session proposal that went stale",
    "mcp__ccd_session_mgmt__stop_session": "stop a builder session that was started for a story",
    "mcp__ccd_session_mgmt__send_message": "send a message to another session",
    "mcp__ccd_session_mgmt__set_session_title": "rename a session in the sidebar",
    "mcp__ccd_session_mgmt__archive_session": "archive a finished session",
    "mcp__ccd_session_mgmt__detach_session": "detach a session from its window",
    "mcp__ccd_sidebar__set_pinned": "pin or unpin a session in the sidebar",
    "mcp__ccd_sidebar__move_sessions": "move sessions between sidebar groups",
    "SendMessage": "continue a subagent that already ran",
    "Bash(olivercode clean*)": "remove the merged, clean worktrees, and keep any that hold unlanded work",
    "Bash(git worktree prune*)": "clear the records of worktrees already deleted",
}


def allow_lines(settings_path: Path) -> list[str]:
    """One line per ALLOW rule: whether the settings hold it, the rule and what it permits."""
    lacking = set(missing_allow(settings_path))
    return [f"  [{'WILL ADD' if a in lacking else 'PRESENT'}] {a}: {ALLOW_WHY[a]}" for a in ALLOW]


# The autoMode rules a builder start needs, so auto mode never denies the session that runs a backlog story. Only the
# owner's own terminal run of install writes them (an agent editing its own oversight settings is what auto mode refuses),
# so an agent run prints them for the owner to add.
def automode_rules(oc_root: Path | None = None) -> dict:
    """The autoMode rules, naming the checkout they were written for (#719)."""
    root = str(oc_root or OC_ROOT)
    return {
        "environment": (
            "OliverCode runs on this machine as one owner thread. The owner's thread starts headless builder sessions "
            "through OliverCode's runner (olivercode dispatch and drain), each builder works one backlog story in its own "
            "worktree and ends with a commit, and the runner validates and lands that commit. The owner of this machine "
            "ran install to set up this workflow.",
            f"OliverCode's own repo is {root}. Its pre-push gate requires a passing scripts/validate.sh "
            "run on the exact tree being pushed.",
        ),
        "allow": (
            "Starting, messaging, titling, pinning, detaching or stopping Claude Code desktop sessions "
            "(mcp__ccd_session__start_session, mcp__ccd_session_mgmt__*) to run a builder for a backlog story, "
            "when the prompt names that story",
            "Listing Claude Code desktop sessions (mcp__ccd_session_mgmt__list_sessions) to find the session that runs "
            "a story's builder",
        ),
    }


AUTOMODE = automode_rules()
DEFAULTS = "$defaults"


def automode_block() -> str:
    """The autoMode block as JSON, for the owner to paste into settings.json."""
    return json.dumps({"autoMode": {k: [DEFAULTS, *v] for k, v in AUTOMODE.items()}}, indent=2)


def _command(script: str, hooks_dir: Path) -> str:
    return f'python3 "{hooks_dir / script}"'


# The exact form _command() writes, from any checkout path. It is the only form install has
# ever written, so nothing looser is needed to recognise an older install.
_MANAGED_COMMAND = re.compile(
    r'python3 "(.+)/scripts/hooks/(' + "|".join(re.escape(s) for s in [m[2] for m in MANAGED] + list(RETIRED)) + r')"')


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


def _is_dead(handler: dict, hooks_dir: Path) -> bool:
    """True for an entry in the exact form `_command()` writes for this checkout whose script is gone."""
    cmd = handler.get("command", "") if isinstance(handler, dict) else ""
    prefix = f'python3 "{hooks_dir}/'
    if not (isinstance(cmd, str) and cmd.startswith(prefix) and cmd.endswith('"')):
        return False
    script = cmd[len(prefix):-1]
    return bool(script) and "/" not in script and '"' not in script and not (hooks_dir / script).exists()


def _strip_managed(hooks: dict, hooks_dir: Path | None = None) -> dict:
    """Each event's hook groups with OliverCode's handlers taken out, and, given hooks_dir, the entries whose
    script is missing from it. A group that held only those handlers is dropped, and an event left with no
    group maps to an empty list."""
    out = {}
    for event, groups in hooks.items():
        out[event] = []
        for group in groups:
            kept = [h for h in group.get("hooks", [])
                    if not _is_managed(h) and not (hooks_dir and _is_dead(h, hooks_dir))]
            # A group the operator left empty stays as it was, so install does not rewrite the file on every run.
            if kept or not group.get("hooks"):
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
    hooks.update(_strip_managed({e: hooks.get(e, []) for e in dict.fromkeys([e for e, _, _ in MANAGED] + list(hooks))}, hooks_dir))
    for event, matcher, script in MANAGED:
        group = {"hooks": [{"type": "command", "command": _command(script, hooks_dir), "timeout": TIMEOUT_S}]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks[event].append(group)
    out["hooks"] = {e: g for e, g in hooks.items() if g}
    perms = out.setdefault("permissions", {})
    if not isinstance(perms, dict) or not isinstance(perms.get("allow", []), list):
        raise ValueError('"permissions.allow" is not a list')
    allow = perms.setdefault("allow", [])
    allow[:] = [a for a in allow if a not in RETIRED_ALLOW]
    allow.extend(a for a in ALLOW if a not in allow)
    return out


def missing_allow(settings_path: Path) -> list[str]:
    """The ALLOW entries the settings lack."""
    try:
        allow = (json.loads(settings_path.read_text()).get("permissions") or {}).get("allow") or []
    except (OSError, ValueError, AttributeError):
        allow = []
    return [a for a in ALLOW if a not in allow]


def dead(settings_path: Path) -> list[str]:
    """The managed-form hook commands in the settings whose script file does not exist. Such an entry makes python exit 2,
    which blocks every tool call it matches, so health fails on one."""
    try:
        current = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
        _check_shape(current)
    except (OSError, ValueError):
        return []
    out = []
    for groups in (current.get("hooks") or {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                m = _MANAGED_COMMAND.fullmatch(cmd) if isinstance(cmd, str) else None
                if m and not (Path(m.group(1)) / "scripts" / "hooks" / m.group(2)).exists():
                    out.append(cmd)
    return out


def missing(settings_path: Path, hooks_dir: Path = HOOKS_DIR) -> list[str]:
    """The managed hook scripts this checkout's install would add and the settings lack."""
    try:
        current = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
        _check_shape(current)
    except (OSError, ValueError):
        current = {}
    present = {(g.get("matcher"), h.get("command")) for groups in (current.get("hooks") or {}).values()
               for g in groups for h in g.get("hooks", []) if isinstance(h, dict)}
    return [script for _, matcher, script in MANAGED if (matcher, _command(script, hooks_dir)) not in present]


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


def managed_hooks(settings: dict) -> dict:
    """Only OliverCode's hook entries from the owner's settings, in the `hooks` shape, so a project-only headless run keeps its gates and guards and nothing else of the owner's (#911)."""
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return {}
    out = {}
    for event, groups in hooks.items():
        kept = [{**g, "hooks": [h for h in g.get("hooks", []) if _is_managed(h)]} for g in groups if isinstance(g, dict)]
        kept = [g for g in kept if g["hooks"]]
        if kept:
            out[event] = kept
    return out


def without(settings: dict) -> dict:
    """Return settings with every OliverCode hook entry taken out and everything else as it was.
    An event, or the "hooks" key itself, that only OliverCode's entries filled is dropped.
    Raises ValueError for a settings shape it cannot read safely."""
    _check_shape(settings)
    out = json.loads(json.dumps(settings))
    perms = out.get("permissions")
    if isinstance(perms, dict) and any(a in (perms.get("allow") or []) for a in ALLOW):
        perms["allow"] = [a for a in perms["allow"] if a not in ALLOW]
        if not perms["allow"]:
            del perms["allow"]
        if not perms:
            del out["permissions"]
    am = out.get("autoMode")
    if isinstance(am, dict) and any(r in (am.get(k) if isinstance(am.get(k), list) else []) for k, rs in AUTOMODE.items() for r in rs):
        for key, rules in AUTOMODE.items():
            if isinstance(am.get(key), list):
                am[key] = [r for r in am[key] if r not in rules]
                if am[key] in ([], [DEFAULTS]):
                    del am[key]
        if not am:
            del out["autoMode"]
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


def automode_missing(settings: dict) -> bool:
    """True when the settings lack any of the AUTOMODE rules."""
    am = settings.get("autoMode") if isinstance(settings, dict) else None
    am = am if isinstance(am, dict) else {}
    return any(r not in (am.get(k) if isinstance(am.get(k), list) else []) for k, rules in AUTOMODE.items() for r in rules)


def _backup_settings(settings_path: Path) -> Path | None:
    """Copy the settings aside to `settings.json.pre-olivercode` (next free number) before autoMode is first written."""
    if not settings_path.is_file():
        return None
    backup = settings_path.with_name(settings_path.name + ".pre-olivercode")
    n = 1
    while backup.exists() or backup.is_symlink():
        n += 1
        backup = settings_path.with_name(f"{settings_path.name}.pre-olivercode.{n}")
    backup.write_text(settings_path.read_text())
    return backup


def _stale_rules(rules: tuple, existing: list) -> list:
    """Entries in `existing` that are one of `rules` written for another checkout path, so a moved checkout leaves no old path behind (#1035)."""
    root = str(OC_ROOT)
    shapes = [re.compile("^" + "(.+?)".join(re.escape(part) for part in r.split(root)) + "$", re.S) for r in rules if root in r]
    return [e for e in existing if isinstance(e, str) and e not in rules and any(m.match(e) for m in shapes)]


def install_automode(settings_path: Path) -> tuple[str, Path | None]:
    """Add the AUTOMODE rules beside the owner's own, after backing the settings up. Returns ("added" or
    "already", the backup path or None). Raises ValueError, leaving the file untouched, for an unreadable shape."""
    current = {}
    if settings_path.is_file():
        text = settings_path.read_text()
        current = json.loads(text) if text.strip() else {}
    if not isinstance(current, dict):
        raise ValueError("the file is not a JSON object")
    am = current.get("autoMode", {})
    if not isinstance(am, dict) or any(not isinstance(am.get(k, []), list) for k in AUTOMODE):
        raise ValueError('"autoMode" is not an object of lists')
    if not automode_missing(current):
        return "already", None
    backup = _backup_settings(settings_path)
    out = json.loads(json.dumps(current))
    am = out.setdefault("autoMode", {})
    for key, rules in AUTOMODE.items():
        lst = am.setdefault(key, [DEFAULTS])
        gone = _stale_rules(rules, lst)
        lst[:] = [e for e in lst if e not in gone]
        lst.extend(r for r in rules if r not in lst)
    _write(settings_path, out)
    return "added", backup
