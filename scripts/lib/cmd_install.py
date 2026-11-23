"""Launcher commands `install` and `uninstall`: link this checkout into ~/.claude and back out again."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import subprocess
import sys
from pathlib import Path

from lib import live_copy as _live_copy
from lib.local_config import claude_dir as _claude_dir
from lib.local_config import OC_ROOT, design_file, fleet_registry_path, load_local, save_local, voice_file

from lib import claude_settings as _claude_settings
from lib import cmd_guide
from lib import queue_shim as _queue_shim
from lib import repo_gates as _repo_gates
from lib.skills_catalog import skill_dirs
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

# The first install's closing text: how work runs, the first steps and the habits that keep it cheap, in 20 lines at most (#972, #991).
INTRODUCTION = """How OliverCode works
  You work in one thread and say what you want. Each request becomes a story on the repo's board.
  `olivercode dispatch N` or `olivercode drain REPO` builds a story in one fresh headless
  Claude session, and the runner validates it and lands it for you. Run `olivercode status`
  to see what is open.

First steps, in order
  1. Register your repos: olivercode discover --root <folder holding your repos> --register
  2. Check this machine: olivercode health
  3. File your first story: say what you want in Claude Code, and it becomes a story on the board.

Using it well
""" + "\n".join(f"  {habit}" for habit in cmd_guide.USING_IT_WELL) + """

Run `olivercode guide` for the full overview."""


RULE_LINKS = {"CLAUDE.md": Path("CLAUDE.md"), "VOICE.md": Path("docs") / "VOICE.md", "DESIGN.md": Path("docs") / "DESIGN.md"}


def _managed_links(oc_root: Path) -> dict[str, Path]:
    """Each link install makes, as its path under ~/.claude -> its source relative to the checkout."""
    links = dict(RULE_LINKS)
    for skill in skill_dirs(oc_root / "skills"):
        links[f"skills/{skill.name}"] = Path("skills") / skill.name
    return links


def override_dir() -> Path:
    """This device's skill overrides, `~/.olivercode/skills`, outside every checkout."""
    from lib import failure_log  # the home folder is shared with the other local state
    return failure_log.home() / "skills"


def wanted_skills(oc_root: Path) -> dict[str, Path]:
    """Each skill name -> the folder ~/.claude/skills links to: an override wins over the shipped skill."""
    wanted = {skill.name: skill for skill in skill_dirs(oc_root / "skills")}
    over = override_dir()
    if over.is_dir():
        for folder in sorted(over.iterdir()):
            if folder.is_dir() and not folder.name.startswith("."):
                wanted[folder.name] = folder
    return wanted


def _is_managed(link: Path, oc_root: Path) -> bool:
    """True for a link into this checkout's skills or into the override folder: install wrote it, so install may move it."""
    target = link.resolve()
    return any(target.is_relative_to(base.resolve()) for base in (oc_root / "skills", override_dir()))


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


def _schedule_replay() -> None:
    """Load the launchd job that replays queued gh writes at each GraphQL reset (`olivercode gh-limit --schedule`, #704).
    Only on a Mac and only for the real home folder, so a test or a relocated HOME never loads a job."""
    real = Path(pwd.getpwuid(os.getuid()).pw_dir) if sys.platform == "darwin" else None
    if real is None or Path.home().resolve() != real.resolve():
        return
    from lib import cmd_ghreplay
    print("  [JOB] " + ("GitHub replay job loaded" if cmd_ghreplay.schedule(True) == 0 else "GitHub replay job failed; run `olivercode gh-limit --schedule`"))


REMOVED_JOBS = tuple("com.olivercode." + name for name in ("city", "workmap", "idle-sessions", "review", "gap-sweep", "burndown", "sweep"))
REMOVED_PAGES = (".olivercode/city.html",)


def retire_removed_jobs(home: Path | None = None, run=subprocess.run) -> list[str]:
    """Unload and delete the launchd jobs of commands the engine no longer has. Returns the labels it removed."""
    folder = (home or Path.home()) / "Library" / "LaunchAgents"
    gone = []
    for label in REMOVED_JOBS:
        plist = folder / f"{label}.plist"
        if not plist.is_file():
            continue
        run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        plist.unlink(missing_ok=True)
        print(f"  [JOB] removed the job {label}, which has no command any more")
        gone.append(label)
    return gone


def retire_removed_pages(home: Path | None = None) -> list[str]:
    """Delete the pages that removed commands wrote under the home folder. Returns the paths it removed, relative to home."""
    folder = home or Path.home()
    gone = []
    for rel in REMOVED_PAGES:
        page = folder / rel
        if not page.is_file():
            continue
        page.unlink()
        print(f"  [PAGE] removed {rel}, which a removed command wrote")
        gone.append(rel)
    return gone


def _retire_removed_jobs() -> None:
    """Remove the jobs and pages of removed commands, under the same real-home rule as the replay job."""
    real = Path(pwd.getpwuid(os.getuid()).pw_dir) if sys.platform == "darwin" else None
    if real is None or Path.home().resolve() != real.resolve():
        return
    retire_removed_jobs()
    retire_removed_pages()


def owner_terminal() -> bool:
    """True when the owner runs install in their own terminal: a terminal on both ends and no Claude Code session
    around it. A session, a pipe or a scheduled job is not the owner."""
    agent = any(os.environ.get(v) for v in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID"))
    return sys.stdin.isatty() and sys.stdout.isatty() and not agent


def _install_automode(settings_path: Path) -> bool:
    """Write the handoff autoMode rules for the owner, or print them for the owner to add. Returns True on a failure."""
    block = _claude_settings.automode_block()
    if not owner_terminal():
        try:
            current = json.loads(settings_path.read_text()) if settings_path.is_file() and settings_path.read_text().strip() else {}
        except (OSError, ValueError):
            current = {}
        if _claude_settings.automode_missing(current):
            print("  [OWNER] autoMode rules for session handoffs not written, since only you running install in a terminal writes them.")
            print("          Run `olivercode install` yourself, or add this at the top level of ~/.claude/settings.json:")
            print("\n".join("          " + line for line in block.splitlines()))
        else:
            print("  [ALREADY] autoMode rules in ~/.claude/settings.json")
        return False
    try:
        result, backup = _claude_settings.install_automode(settings_path)
    except ValueError as exc:
        print(f"  [FAIL] autoMode rules not written to ~/.claude/settings.json ({exc})")
        return True
    print(f"  [{result.upper()}] autoMode rules in ~/.claude/settings.json" + (f" (previous settings kept at {backup})" if backup else ""))
    return False


def fleet_repo_step(dest: Path, ask=None, push=None) -> str:
    """Makes the fleet folder a local git repo with its files in one commit, prints its path and, on a first install, offers a private
    GitHub copy once (#993). `ask` is None outside the owner's terminal, where nothing is pushed. Returns the error, or "" when it worked."""
    from lib.cmd_initfleet import command_init_fleet, make_local_repo, scaffold_local
    if not (dest / "repo-profiles.json").exists():
        scaffold_local(dest)
    made, error = make_local_repo(dest)
    if error:
        print(f"The fleet folder {dest} could not be made a git repo: {error}")
        return error
    print(f"Fleet repo: {dest}")
    if made and ask is not None and ask("Push a private copy of the fleet repo to GitHub now? [y/N] ").strip().lower() in ("y", "yes"):
        (push or command_init_fleet)(["--dir", str(dest)])
    return ""


def design_step(ask=None) -> str:
    """Asks once for the owner's own design file (#995). A path to an existing file is saved as `designFile` in the local config, and a blank
    answer keeps the shipped docs/DESIGN.md. Either way the question is not asked again, because `designAsked` is saved. `ask` is None outside the
    owner's terminal, where nothing is asked. Returns the saved path, or "" when none was saved."""
    local = load_local()
    if ask is None or "designFile" in local or local.get("designAsked"):
        return ""
    answer = ask("Path to your own design file, or Enter to keep the shipped docs/DESIGN.md: ").strip()
    own = Path(answer).expanduser() if answer else None
    updates = {"designAsked": True}
    if own is not None and own.is_file():
        updates["designFile"] = str(own)
        print(f"Design file: {own}, linked as ~/.claude/DESIGN.md below.")
    elif answer:
        print(f"{answer} is not a file, so the shipped docs/DESIGN.md stays. Set designFile in olivercode.local.json to change it.")
    else:
        print("Design file: the shipped docs/DESIGN.md. Set designFile in olivercode.local.json to change it.")
    save_local(updates)
    return str(own) if "designFile" in updates else ""


def registered_repos() -> list[tuple[str, Path]]:
    """OliverCode and each cloned repo in the fleet registry: the repos install gives a board (#994)."""
    from lib.repo_profiles import iter_fleet, load_repo_profiles
    profiles, _ = load_repo_profiles(OC_ROOT)
    return [("OliverCode", OC_ROOT), *[(name, path) for name, _, path in iter_fleet(profiles, OC_ROOT.parent) if (path / ".git").exists()]]


def board_step(repos: list[tuple[str, Path]]) -> str:
    """Install's board step (#994). With gh signed in and holding the project scope, it runs `backlog-setup --apply` for each repo whose
    backlog config is absent or still the example's, names that config in the repo's CLAUDE.md and prints the board URL. A repo with a
    valid config is left alone. Returns the line that stopped the step before any board, or "" when it ran."""
    from lib import backlog_setup
    from lib.cmd_fleet import command_backlog_setup
    from lib.health_checks import gh_ready
    problem = gh_ready()
    if problem:
        print(problem)
        return problem
    for name, path in repos:
        try:
            if backlog_setup.load_config(backlog_setup.config_path(path)) is not None:
                continue
            if command_backlog_setup([str(path), "--apply"]) != 0:
                print(f"{name}: backlog-setup did not finish. Fix the cause, then run `olivercode backlog-setup {path} --apply`")
                continue
            config = backlog_setup.load_config(backlog_setup.config_path(path))
        except backlog_setup.SetupError as error:
            print(f"{name}: {error}")
            continue
        rel = backlog_setup.config_path(path).relative_to(path)
        claude = path / "CLAUDE.md"
        if claude.is_file() and "backlog-config.json" not in claude.read_text(encoding="utf-8", errors="ignore"):
            claude.write_text(claude.read_text(encoding="utf-8", errors="ignore") + f"\nBacklog config: `{rel}` names this repo's board.\n", encoding="utf-8")
        if config is None:
            print(f"{name}: the board was not confirmed. Run `olivercode backlog-setup {path}` to see why")
        else:
            print(f"{name}: board https://github.com/users/{config['projectOwner']}/projects/{config.get('projectNumber', 0)}, config {rel}")
    return ""


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
    live = _live_copy.problem(oc_root)
    if live:
        print(f"  [FAIL] {live}")
        return 1
    claude_dir = _claude_dir()
    skills_dir = claude_dir / "skills"
    first_install = _read_record(claude_dir) is None
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
    # The hooks are built here, since a fresh clone holds only their sources (HOOK-OUTPUTS-1)
    # and this checkout's .githooks links point at the built files.
    _repo_gates.hook_templates(oc_root)
    backups: list[str] = []
    moved_links = _dangling_from_install(claude_dir, oc_root)

    def _link(target: Path, source: Path, keep_own: bool = False) -> str:
        """Point target at source. Returns a one-word status. With keep_own, a file or link the user put there stays as it is (#719)."""
        if keep_own and (target.exists() or target.is_symlink()) and not (target.is_symlink() and (_is_managed_rule(target) or target.resolve() == source.resolve())):
            return "kept"
        if target.is_symlink():
            if target.resolve() == source.resolve():
                return "already"
            # A link into this checkout or the override folder is install's own, so it moves in place.
            if str(target.relative_to(claude_dir)) in moved_links or _is_managed(target, oc_root):
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
    def _is_managed_rule(link: Path) -> bool:
        """True for a rules link install wrote: it points into this checkout or at the configured voice or design file."""
        target = link.resolve()
        return any(target == base or target.is_relative_to(base) for base in (oc_root.resolve(), voice_file(oc_root).resolve(), design_file(oc_root).resolve()))

    status = _link(claude_dir / "VOICE.md", voice_file(oc_root), keep_own=True)
    print(f"  [{status.upper()}] ~/.claude/VOICE.md")
    design_step(input if owner_terminal() else None)
    # DESIGN.md is read on visual work only, so CLAUDE.md does not import it.
    status = _link(claude_dir / "DESIGN.md", design_file(oc_root), keep_own=True)
    print(f"  [{status.upper()}] ~/.claude/DESIGN.md")

    linked = already = 0
    wanted = wanted_skills(oc_root)
    for name, source in wanted.items():
        result = _link(skills_dir / name, source)
        if result == "already":
            already += 1
        else:
            linked += 1
    print(f"  [OK] skills: {linked} linked, {already} already correct")
    # A skill this checkout or the override folder removed leaves a dangling link that install wrote.
    retired = sorted(p.name for p in skills_dir.iterdir() if p.is_symlink() and not p.exists()
                     and (Path(os.readlink(p)) == oc_root / "skills" / p.name
                          or Path(os.readlink(p)).parent == override_dir()))
    for name in retired:
        (skills_dir / name).unlink()
    if retired:
        print(f"  [REMOVED] links to skills this checkout no longer has: {', '.join(retired)}")
    from lib import failure_log  # the hooks log blocked commits only where this folder exists
    failure_log.home().mkdir(parents=True, exist_ok=True)
    # A release that moves a state file moves the user's copy once, with a backup (#762).
    from lib import state_migrations
    for line in state_migrations.run(oc_root):
        print(f"  [MIGRATED] {line}")
    expected = {k: oc_root / rel for k, rel in RULE_LINKS.items()}
    expected.update({f"skills/{name}": source for name, source in wanted.items()})
    _write_record(claude_dir, {k: os.readlink(claude_dir / k) for k, src in expected.items()
                               if (claude_dir / k).is_symlink() and (claude_dir / k).resolve() == src.resolve()})

    broken_settings = False
    # Every repo's validate.sh takes a queue slot through this helper, so no repo script names this checkout (#572).
    try:
        status = _queue_shim.install(oc_root, backups)
        print(f"  [{status.upper()}] ~/.local/bin/validate-queue")
    except OSError as exc:
        print(f"  [FAIL] ~/.local/bin/validate-queue could not be written ({exc}); validate.sh runs unqueued until `olivercode install` succeeds")
        broken_settings = True

    try:
        for line in _queue_shim.install_launcher(oc_root, backups):
            print(line)
    except OSError as exc:
        print(f"  [FAIL] `olivercode` could not be put on the PATH ({exc}); run `olivercode install` again once it is fixed")
        broken_settings = True

    # The Claude Code hooks are what hold the rules in every session, so install owns
    # them like the links above; claude_settings leaves the operator's own keys alone.
    try:
        result = _claude_settings.install(claude_dir / "settings.json")
        print(f"  [{result.upper()}] Claude Code hooks in ~/.claude/settings.json")
    except ValueError as exc:  # invalid JSON, or a shape the merge would have to guess at
        print(f"  [FAIL] ~/.claude/settings.json could not be merged ({exc}); left as it is, hooks not installed")
        broken_settings = True
    else:
        broken_settings = _install_automode(claude_dir / "settings.json") or broken_settings

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

    _schedule_replay()
    _retire_removed_jobs()

    broken = _broken_links(skills_dir)
    if broken:
        print(f"  [FAIL] broken symlinks in ~/.claude/skills/: {', '.join(broken)}")

    untouched = sorted(
        p.name for p in skills_dir.iterdir()
        if p.name and not p.name.startswith(".")
        and not (p.is_symlink() and p.exists() and (p.resolve().is_relative_to(oc_root) or _is_managed(p, oc_root)))
    )
    if untouched:
        print(f"  [KEPT] {len(untouched)} entr(y/ies) not managed by this checkout, left as-is: "
              f"{', '.join(untouched)}")
        print("         `olivercode discover --root <dir>` classifies them.")

    print()
    if backups:
        print("Backed up and kept — merge these in deliberately, since they are usually")
        print("the rules you already had (docs/SETUP.md Step 3):")
        for b in backups:
            print(f"  {b}")
        print()
    fleet_repo_step(fleet_registry_path(), ask=input if owner_terminal() else None)
    if owner_terminal():
        board_step(registered_repos())
    else:
        print("Board step skipped here. Run `olivercode install` in your own terminal, or `olivercode backlog-setup DIR --apply` for each repo.")
    if first_install:
        print(INTRODUCTION)
    else:
        print("Run `olivercode guide` to see how work runs.")
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
    claude_dir = _claude_dir()
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

    for name, rel in RULE_LINKS.items():
        path, note = claude_dir / name, ""
        if path.is_symlink() and (_points_into(path, (root / rel).resolve()) or _points_into(path, voice_file(root).resolve()) or name in moved_links):
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
            ours = _points_into(entry, root / "skills") or _points_into(entry, override_dir().resolve())
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

    shim = _queue_shim.uninstall(oc_root)
    print(f"  [{shim.upper()}] ~/.local/bin/validate-queue")
    for line in _queue_shim.uninstall_launcher(oc_root):
        print(line)

    leftovers = [b for name in RULE_LINKS for b in _backups(claude_dir / name)]
    leftovers += _backups(_queue_shim.shim_path()) + _backups(_queue_shim.launcher_path())
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
