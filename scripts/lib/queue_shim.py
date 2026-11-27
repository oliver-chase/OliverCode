"""Puts `olivercode` itself on the PATH (#777): a symlink at ~/.local/bin/olivercode to this checkout's launcher, plus a marked
PATH block in the zsh and bash startup files when ~/.local/bin is not on the PATH yet. Install writes it, uninstall removes it,
and health checks it.
"""

from __future__ import annotations

import os
from pathlib import Path

FIX = "run `olivercode install`"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _set_aside(path: Path, backups: list[str]) -> None:
    """Rename `path` to a free backup name, never replacing an earlier backup, and add the name to `backups`."""
    from lib.cmd_install import BACKUP_SUFFIX
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    n = 1
    while backup.exists() or backup.is_symlink():
        n += 1
        backup = path.with_name(f"{path.name}{BACKUP_SUFFIX}.{n}")
    path.rename(backup)
    backups.append(str(backup))


def remove_old_shim() -> bool:
    """Remove ~/.local/bin/validate-queue left by an earlier install when it is the old two-line shim. True when it removed one."""
    path = Path.home() / ".local" / "bin" / "validate-queue"
    if not path.is_symlink() and "validate_queue.py" in (_read(path) or ""):
        path.unlink()
        return True
    return False


# --- the `olivercode` command on the PATH (#777) ---

LAUNCHER_NAME = "olivercode"
BLOCK_START = "# >>> olivercode PATH >>>"
BLOCK_END = "# <<< olivercode PATH <<<"
BLOCK = f'{BLOCK_START}\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n{BLOCK_END}\n'


def launcher_path() -> Path:
    return Path.home() / ".local" / "bin" / LAUNCHER_NAME


def launcher_target(oc_root: Path) -> Path:
    return Path(oc_root).resolve() / "scripts" / "olivercode"


def profile_files() -> list[Path]:
    """The startup files a new zsh or bash shell reads, login or not: .zshenv covers every zsh, .bashrc a non-login bash,
    and the first bash login file that exists (or .bash_profile) a login bash."""
    home = Path.home()
    login = next((home / n for n in (".bash_profile", ".bash_login", ".profile") if (home / n).exists()), home / ".bash_profile")
    return [home / ".zshenv", home / ".bashrc", login]


def _local_bin_on_path() -> bool:
    here = str(Path.home() / ".local" / "bin")
    return here in os.environ.get("PATH", "").split(os.pathsep)


def _has_block(path: Path) -> bool:
    return BLOCK_START in (_read(path) or "")


def _strip_block(text: str) -> str:
    start = text.find(BLOCK_START)
    end = text.find(BLOCK_END, start)
    if start < 0 or end < 0:
        return text
    return text[:start] + text[end + len(BLOCK_END):].lstrip("\n")


def _points_at_olivercode(path: Path) -> bool:
    """True for a symlink whose target is some checkout's scripts/olivercode, live or gone."""
    return path.is_symlink() and os.readlink(path).endswith("/scripts/olivercode")


def install_launcher(oc_root: Path, backups: list[str]) -> list[str]:
    """Link ~/.local/bin/olivercode to this checkout and add the PATH block where ~/.local/bin is not on the PATH.
    Returns the status lines to print. A link to another checkout, or a dead one, is replaced, so a moved checkout
    leaves no stale path. A file or link that is not an olivercode launcher is backed up like the shim."""
    path, target = launcher_path(), launcher_target(oc_root)
    out: list[str] = []
    if path.is_symlink() and Path(os.readlink(path)) == target:
        out.append("  [ALREADY] ~/.local/bin/olivercode")
    else:
        status = "linked"
        if path.exists() or path.is_symlink():
            if _points_at_olivercode(path):
                path.unlink()
            else:
                _set_aside(path, backups)
                status = "backed-up"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        out.append(f"  [{status.upper()}] ~/.local/bin/olivercode")
    if _local_bin_on_path():
        return out
    wrote = []
    for f in profile_files():
        if _has_block(f):
            continue
        old = _read(f) or ""
        f.write_text(old + ("" if not old or old.endswith("\n") else "\n") + BLOCK, encoding="utf-8")
        wrote.append(f.name)
    out.append(f"  [{'ADDED' if wrote else 'ALREADY'}] ~/.local/bin on the PATH in new shells" + (f" ({', '.join(wrote)})" if wrote else ""))
    return out


def uninstall_launcher(oc_root: Path) -> list[str]:
    """Remove the launcher link when it is an olivercode link (this checkout's, or a moved one's), and the PATH blocks."""
    path, out = launcher_path(), []
    if _points_at_olivercode(path):
        path.unlink()
        out.append("  [REMOVED] ~/.local/bin/olivercode")
    elif path.exists() or path.is_symlink():
        out.append("  [KEPT] ~/.local/bin/olivercode (it is not a link install wrote)")
    else:
        out.append("  [ABSENT] ~/.local/bin/olivercode")
    stripped = []
    for f in profile_files():
        text = _read(f)
        if text and BLOCK_START in text:
            f.write_text(_strip_block(text), encoding="utf-8")
            stripped.append(f.name)
    if stripped:
        out.append(f"  [REMOVED] PATH block from {', '.join(stripped)}")
    return out


def launcher_problem(oc_root: Path) -> str | None:
    """Why `olivercode` would not run from a new shell, or None. Needs the link to this checkout, and ~/.local/bin on the
    PATH either now or through the profile block in a zsh and a bash startup file."""
    path = launcher_path()
    if not path.is_symlink() or Path(os.readlink(path)) != launcher_target(oc_root):
        return f"`olivercode` is not linked to this checkout at {path}, so a new shell will not find it. {FIX.capitalize()}"
    if not _local_bin_on_path():
        zsh, *bash = profile_files()
        if not (_has_block(zsh) and any(_has_block(f) for f in bash)):
            return f"{path.parent} is not on the PATH of a new shell, so `olivercode` is not found. {FIX.capitalize()}"
    return None
