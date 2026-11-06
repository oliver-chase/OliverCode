"""Launcher commands `install` and `uninstall`: link this checkout into ~/.claude and back out again."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from lib import claude_settings as _claude_settings
from lib import repo_gates as _repo_gates
from lib.repo_profiles import registry_file
from lib.skill_links import broken_links as _broken_links


BACKUP_SUFFIX = ".pre-olivercode"


def _backups(path: Path) -> list[Path]:
    """Install's backups of path, oldest first: `<name>.pre-olivercode`, then `.2`, `.3`..."""
    if not path.parent.is_dir():
        return []
    found = []
    for b in path.parent.iterdir():
        if not b.name.startswith(path.name + BACKUP_SUFFIX):
            continue
        rest = b.name[len(path.name + BACKUP_SUFFIX):]
        if rest == "" or (rest[:1] == "." and rest[1:].isdigit()):
            found.append((int(rest[1:]) if rest else 1, b))
    return [b for _, b in sorted(found)]


INSTALL_RECORD = ".olivercode-install.json"


def _managed_links(oc_root: Path) -> dict[str, Path]:
    """Each link install makes, as its path under ~/.claude -> its source relative to the checkout."""
    links = {"CLAUDE.md": Path("CLAUDE.md"), "VOICE.md": Path("docs") / "VOICE.md"}
    for skill in sorted(p for p in (oc_root / "skills").iterdir() if (p / "SKILL.md").is_file()):
        links[f"skills/{skill.name}"] = Path("skills") / skill.name
    return links


def _read_record(claude_dir: Path) -> dict | None:
    """The links the last install wrote, as path under ~/.claude -> stored target. None when
    no install has written a record; an unreadable record counts as recording nothing."""
    path = claude_dir / INSTALL_RECORD
    if not path.is_file():
        return None
    try:
        links = json.loads(path.read_text()).get("links", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return links if isinstance(links, dict) else {}


def _write_record(claude_dir: Path, links: dict[str, str]) -> None:
    path = claude_dir / INSTALL_RECORD
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"links": links}, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _dangling_from_install(claude_dir: Path, oc_root: Path) -> set[str]:
    """The links under ~/.claude that dangle and that an OliverCode install wrote, as after the
    checkout moved. A dangling link alone proves nothing: it may point at a drive that is not
    mounted. The install record decides when there is one. For an install made before the
    record existed, two or more of install's links must dangle into the same folder, laid out
    the way a checkout is."""
    record = _read_record(claude_dir)
    managed = _managed_links(oc_root)
    dangling = {k: claude_dir / k for k in managed
                if (claude_dir / k).is_symlink() and not (claude_dir / k).exists()}
    if record is not None:
        return {k for k, link in dangling.items() if os.readlink(link) == record.get(k)}
    bases = {}
    for k, link in dangling.items():
        rel = managed[k]
        stored = Path(os.readlink(link))
        stored = stored if stored.is_absolute() else link.parent / stored
        if stored.parts[-len(rel.parts):] == rel.parts:
            bases[k] = Path(*stored.parts[:-len(rel.parts)])
    counts = {b: list(bases.values()).count(b) for b in bases.values()}
    return {k for k, b in bases.items() if counts[b] >= 2}


def command_install(oc_root: Path) -> int:
    """Activate this checkout: symlink CLAUDE.md, the voice and every skill into ~/.claude.

    This is the step that makes the rules load in every session from any directory.
    Doing it by hand is four commands and fails silently in two ways -- `ln` into a
    missing ~/.claude/skills dies with a bare "No such file or directory", and
    replacing an existing real CLAUDE.md destroys rules the operator may not have
    copied anywhere yet.

    Never destructive: a real file or any other link at a target path, a dangling one or
    one into another OliverCode checkout included, is moved aside to `<name>.pre-olivercode`
    and the path is reported, because that file is usually the operator's entire
    accumulated ruleset and docs/SETUP.md Step 3 exists to merge it back in
    deliberately. Only a link an OliverCode install wrote that now dangles, because its
    checkout moved, is replaced in place. `uninstall` restores the backup. Install records
    the links it wrote in ~/.claude/.olivercode-install.json so uninstall need not guess.
    """
    claude_dir = Path.home() / ".claude"
    skills_dir = claude_dir / "skills"
    print("OliverCode install — activating this checkout in ~/.claude")
    print("=" * 40)

    # A plain file sitting where a directory belongs is rare but real, and an unhandled
    # FileExistsError traceback is a poor first impression from the first command a fork
    # runs. Say what is wrong and what to do about it.
    for needed in (claude_dir, skills_dir):
        if needed.exists() and not needed.is_dir():
            print(f"  [FAIL] {needed} exists but is not a directory.")
            print("         Move or remove it, then re-run `olivercode install`.")
            return 1
    skills_dir.mkdir(parents=True, exist_ok=True)
    backups: list[str] = []
    moved_links = _dangling_from_install(claude_dir, oc_root)

    def _link(target: Path, source: Path) -> str:
        """Point target at source. Returns a one-word status."""
        if target.is_symlink():
            if target.resolve() == source.resolve():
                return "already"
            if str(target.relative_to(claude_dir)) in moved_links:
                target.unlink()
                target.symlink_to(source)
                return "relinked"
        if target.exists() or target.is_symlink():
            # BACKUP-COLLISION-1: rename() overwrites an existing destination on POSIX, so the
            # backup name keeps counting until it is free and no earlier backup is ever replaced.
            backup = target.with_name(target.name + BACKUP_SUFFIX)
            n = 1
            while backup.exists() or backup.is_symlink():  # a backed-up link may dangle
                n += 1
                backup = target.with_name(f"{target.name}.pre-olivercode.{n}")
            target.rename(backup)
            backups.append(str(backup))
            target.symlink_to(source)
            return "backed-up"
        target.symlink_to(source)
        return "linked"

    status = _link(claude_dir / "CLAUDE.md", oc_root / "CLAUDE.md")
    print(f"  [{status.upper()}] ~/.claude/CLAUDE.md")
    # CLAUDE.md imports the voice by this fixed path. A relative import from a symlinked
    # CLAUDE.md has no documented base directory, so it could silently load nothing.
    status = _link(claude_dir / "VOICE.md", oc_root / "docs" / "VOICE.md")
    print(f"  [{status.upper()}] ~/.claude/VOICE.md")

    linked = already = 0
    for skill in sorted(p for p in (oc_root / "skills").iterdir() if (p / "SKILL.md").is_file()):
        result = _link(skills_dir / skill.name, skill)
        if result == "already":
            already += 1
        else:
            linked += 1
    print(f"  [OK] skills: {linked} linked, {already} already correct")
    # A skill this checkout removed leaves its link dangling into the checkout's own skills folder.
    # Install wrote that link, so install removes it.
    retired = sorted(p.name for p in skills_dir.iterdir() if p.is_symlink() and not p.exists()
                     and Path(os.readlink(p)) == oc_root / "skills" / p.name)
    for name in retired:
        (skills_dir / name).unlink()
    if retired:
        print(f"  [REMOVED] links to skills this checkout no longer has: {', '.join(retired)}")
    _write_record(claude_dir, {k: os.readlink(claude_dir / k) for k, rel in _managed_links(oc_root).items()
                               if (claude_dir / k).is_symlink() and (claude_dir / k).resolve() == (oc_root / rel).resolve()})

    # The Claude Code hooks are what hold the rules in every session, so install owns
    # them like the links above; claude_settings leaves the operator's own keys alone.
    broken_settings = False
    try:
        result = _claude_settings.install(claude_dir / "settings.json")
        print(f"  [{result.upper()}] Claude Code hooks in ~/.claude/settings.json")
    except ValueError as exc:  # invalid JSON, or a shape the merge would have to guess at
        print(f"  [FAIL] ~/.claude/settings.json could not be merged ({exc}); left as it is, hooks not installed")
        broken_settings = True

    # A fresh clone has core.hooksPath unset, so git runs none of this checkout's own gates.
    # Set it only when unset and only in this checkout's own repo; a value the owner chose stays.
    own_repo = subprocess.run(["git", "-C", str(oc_root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if _repo_gates.has_gates(oc_root) and own_repo.stdout.strip() and Path(own_repo.stdout.strip()).resolve() == oc_root.resolve():
        set_hooks = ["git", "-C", str(oc_root), "config", "core.hooksPath", ".githooks"]
        fix = shlex.join(set_hooks)
        problem = _repo_gates.gate_problem(oc_root)
        if not _repo_gates.hooks_path(oc_root):
            done = subprocess.run(set_hooks, capture_output=True).returncode == 0
            print("  [SET] core.hooksPath in the OliverCode checkout" if done
                  else f"  [WARN] could not set core.hooksPath; run `{fix}`")
        elif not problem:
            print("  [ALREADY] core.hooksPath in the OliverCode checkout")
        elif "not executable" in problem:
            print(f"  [WARN] {problem}; to fix it run `chmod +x {shlex.quote(str(oc_root / '.githooks' / 'pre-commit'))}`")
        else:
            print(f"  [WARN] {problem}; to fix it run `{fix}`")

    broken = _broken_links(skills_dir)
    if broken:
        print(f"  [FAIL] broken symlinks in ~/.claude/skills/: {', '.join(broken)}")

    untouched = sorted(
        p.name for p in skills_dir.iterdir()
        if p.name and not p.name.startswith(".")
        and not (p.is_symlink() and p.exists() and str(p.resolve()).startswith(str(oc_root)))
    )
    if untouched:
        print(f"  [KEPT] {len(untouched)} entr(y/ies) not managed by this checkout, left as-is: "
              f"{', '.join(untouched)}")
        print("         `olivercode discover --root <dir>` classifies them.")

    print()
    if backups:
        print("Backed up, NOT deleted — merge these in deliberately, they are usually")
        print("the rules you already had (docs/SETUP.md Step 3):")
        for b in backups:
            print(f"  {b}")
        print()
    print(f"Next: register the repo in {registry_file(oc_root, 'repo-profiles.json')}, then `olivercode conform` to verify.")
    return 1 if broken or broken_settings else 0


def command_uninstall(oc_root: Path) -> int:
    """Undo `install`: remove what it wrote in ~/.claude and nothing else.

    A link is removed when it points into this checkout, or when it dangles and an
    OliverCode install wrote it (a checkout that moved), by the install record or, for an
    older install, by corroboration (see _dangling_from_install). Every other link stays,
    and so does a link into another live checkout. The install record goes too.
    The newest `<name>.pre-olivercode` backup install made is moved back once its path is
    free, and any older one is listed. The hook entries come out of settings.json by the
    same rule install uses to replace them, and every other key stays. Idempotent.

    `core.hooksPath` and each repo's `.githooks/` come from `sync-hooks`,
    so they stay; docs/SETUP.md "Backing out" covers them.
    """
    claude_dir = Path.home() / ".claude"
    skills_dir = claude_dir / "skills"
    root = oc_root.resolve()
    moved_links = _dangling_from_install(claude_dir, oc_root) if claude_dir.is_dir() else set()
    print("OliverCode uninstall — removing what install wrote in ~/.claude")
    print("=" * 40)

    def _points_into(link: Path, base: Path) -> bool:
        # resolve() follows a link whose target is gone as far as it can, so a skill
        # deleted from the checkout after install still reads as this checkout's.
        target = link.resolve()
        return target == base or target.is_relative_to(base)

    def _restore(path: Path) -> bool:
        backups = _backups(path)
        if backups and not (path.exists() or path.is_symlink()):
            backups[-1].rename(path)  # the newest is what sat here right before the last install
            return True
        return False

    for name, rel in (("CLAUDE.md", Path("CLAUDE.md")), ("VOICE.md", Path("docs") / "VOICE.md")):
        path, note = claude_dir / name, ""
        if path.is_symlink() and (_points_into(path, (root / rel).resolve()) or name in moved_links):
            if not path.exists():
                note = f" (it pointed at {os.readlink(path)}, which is gone)"
            path.unlink()
            status = "restored" if _restore(path) else "removed"
        elif _restore(path):
            status = "restored"
        elif path.exists() or path.is_symlink():
            status, note = "kept", " (it is not a link install wrote)"
        else:
            status = "absent"
        print(f"  [{status.upper()}] ~/.claude/{name}{note}")

    removed = dangling = restored = 0
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_symlink():
                continue
            ours = _points_into(entry, root / "skills")
            moved = not ours and f"skills/{entry.name}" in moved_links
            if ours or moved:
                entry.unlink()
                removed += 1
                dangling += moved
        bases = {b.name.split(BACKUP_SUFFIX)[0] for b in skills_dir.iterdir() if BACKUP_SUFFIX in b.name}
        restored = sum(_restore(skills_dir / base) for base in sorted(bases))
    moved_note = f" ({dangling} of them dangling from a checkout that moved)" if dangling else ""
    print(f"  [OK] skills: {removed} link(s) removed{moved_note}, {restored} backup(s) restored")

    broken_settings = False
    try:
        result = _claude_settings.remove(claude_dir / "settings.json")
        print(f"  [{result.upper()}] Claude Code hooks in ~/.claude/settings.json")
    except ValueError as exc:
        print(f"  [FAIL] ~/.claude/settings.json could not be read ({exc}); left as it is, hooks not removed")
        broken_settings = True

    leftovers = [b for name in ("CLAUDE.md", "VOICE.md") for b in _backups(claude_dir / name)]
    if skills_dir.is_dir():
        leftovers += sorted(b for b in skills_dir.iterdir() if BACKUP_SUFFIX in b.name)
    (claude_dir / INSTALL_RECORD).unlink(missing_ok=True)
    print()
    if leftovers:
        print("Older backups left in place. An earlier install made each one, or something")
        print("now sits at its original path. Merge them back deliberately:")
        for b in leftovers:
            print(f"  {b}")
        print()
    if (claude_dir / f"skills{BACKUP_SUFFIX}").exists():
        print(f"~/.claude/skills{BACKUP_SUFFIX} is your own copy from docs/SETUP.md Step 2; uninstall leaves it.")
        print()
    print("Next: unset core.hooksPath in each governed repo (docs/SETUP.md \"Backing out\").")
    return 1 if broken_settings else 0
