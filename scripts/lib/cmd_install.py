"""Launcher commands `install` and `uninstall`: link this checkout into ~/.claude and back out again."""

from __future__ import annotations

import json
import os
import plistlib
import pwd
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lib import launchd
from lib import live_copy as _live_copy
from lib.local_config import claude_dir as _claude_dir
from lib.local_config import DEFAULTS, OC_ROOT, design_file, local_path, private_repos, voice_file

from lib import claude_settings as _claude_settings
from lib import cmd_guide, failure_log, placement, repo_state
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
CITY_SHORTCUT = "OliverCode City.html"
CITY_SHORTCUT_WEBLOC = "OliverCode City.webloc"  # the shortcut before #1372: macOS refuses to open a web link to a local file, so update replaces it

# The first install's closing text: how work runs, the first steps and the habits that keep it cheap, in 20 lines at most (#972, #991).
INTRODUCTION = """How OliverCode works
  You work in one thread and say what you want. Each request becomes a story on the repo's board.
  `olivercode dispatch N` or `olivercode drain REPO` builds a story in one fresh headless Claude session, and the runner validates it and lands it for you.
  The thread that started a run is the one to steer it. `olivercode status` answers status from any thread or terminal at no token cost.

First steps, in order
  1. Find your repos: olivercode discover --root <folder holding your repos>
  2. Check this machine: olivercode health
  3. File your first story: say what you want in Claude Code, then build it with `olivercode dispatch N` or `olivercode drain REPO`. A chat never builds a board story by hand.

Using it well
""" + "\n".join(f"  {habit}" for habit in cmd_guide.USING_IT_WELL) + """

Run `olivercode guide` for the full overview."""

# Install cannot sign the owner in or set their git identity, and a session or a pipe never reaches the board step that checks gh (#1509).
OWNER_STEPS = """Steps only you can take, which install cannot do for you (skip any you have done)
  gh auth login                              sign in to GitHub
  gh auth refresh -s project                 add the project scope the board needs
  claude                                     sign in to Claude Code, then exit
  git config --global user.name "Your Name"
  git config --global user.email "<your email>\""""


def closing_lines(oc_root: Path) -> str:
    """Install's last lines on every install: the status steps from `olivercode guide status` and a pointer to the adoption skill (#1059)."""
    steps = "\n".join(f"  {step}" for step in cmd_guide.status_steps(oc_root))
    return f"""Follow a run from a terminal (`olivercode guide status` prints these steps again)
{steps}

Walk through the rest of setup: say "set up OliverCode" in Claude Code, and the olivercode-adoption skill takes you through it."""


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


def _load_record(claude_dir: Path) -> dict | None:
    """The install record as a dict. None when no install has written one; an unreadable record counts as empty."""
    path = claude_dir / INSTALL_RECORD
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_record(claude_dir: Path) -> dict | None:
    """The links the last install wrote, as path under ~/.claude -> stored target. None when no install has written a record."""
    record = _load_record(claude_dir)
    links = (record or {}).get("links", {})
    return None if record is None else links if isinstance(links, dict) else {}


def _write_record(claude_dir: Path, links: dict[str, str], city_shortcut: bool = False) -> None:
    path = claude_dir / INSTALL_RECORD
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"links": links, "city_shortcut": city_shortcut}, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _record_city(claude_dir: Path) -> bool:
    """True when an install wrote the City shortcut, so install never writes it again and uninstall removes it."""
    return (_load_record(claude_dir) or {}).get("city_shortcut") is True


def _desktop() -> Path:
    return Path.home() / "Desktop"


def _city_shortcut(oc_root: Path, claude_dir: Path, desktop: Path | None = None) -> bool:
    """Put an OliverCode City shortcut on the Desktop, once: a link to city.html, which opens in the default browser. The page is
    written first when it is missing, so the shortcut never opens a missing file. Returns whether install has added the shortcut,
    which stays True after the owner deletes it. A shortcut already on the Desktop that install did not write is left alone. An
    earlier install's .webloc, which macOS cannot open, is removed and replaced by the link."""
    from lib import city  # local import: city reads this module's figures
    recorded = _record_city(claude_dir)
    if not city.enabled():
        return recorded
    desktop = desktop or _desktop()
    legacy = desktop / CITY_SHORTCUT_WEBLOC
    replacing = recorded and (legacy.is_symlink() or legacy.exists())
    if replacing:
        legacy.unlink()
        print(f"  [REMOVED] ~/Desktop/{CITY_SHORTCUT_WEBLOC}")
    link = desktop / CITY_SHORTCUT
    if (recorded and not replacing) or link.exists() or link.is_symlink() or not desktop.is_dir():
        return recorded
    page = city.page_path()
    if not page.exists():
        city.refresh(oc_root)
    if not page.exists():
        print(f"  [WARN] ~/Desktop/{CITY_SHORTCUT} not written: City could not be written to {page} yet. Run `olivercode status page` and install again.")
        return False
    link.symlink_to(page)
    print(f"  [ADDED] ~/Desktop/{CITY_SHORTCUT}")
    return True


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


def _real_home() -> bool:
    """True on a Mac when HOME is the real home folder, so a test or a relocated HOME never loads or removes a job."""
    return sys.platform == "darwin" and Path.home().resolve() == Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def _unused(path: Path, sep: str) -> Path:
    """path, or path plus `sep` and the first number from 2 up that is free (a link that dangles still counts as taken)."""
    found, n = path, 1
    while found.exists() or found.is_symlink():
        n += 1
        found = path.with_name(f"{path.name}{sep}{n}")
    return found


def _schedule_jobs() -> None:
    """Load the launchd job that replays queued gh writes at each GraphQL reset (`olivercode gh-limit --schedule`, #704)
    and the daily maintenance job (`olivercode maintain --schedule`, #1395). Only on a Mac and only for the real home folder, so a test or a relocated HOME never loads a job."""
    if not _real_home():
        return
    from lib import cmd_ghreplay, maintain
    for name, module, command in (("GitHub replay job", cmd_ghreplay, "gh-limit"), ("daily maintenance job", maintain, "maintain")):
        if os.environ.get("XPC_SERVICE_NAME") == module.LABEL:
            continue  # `maintain --fix` runs install from inside its own job, and reloading that job would kill the run
        print(f"  [JOB] {name} " + ("loaded" if module.schedule(True) == 0 else f"failed; run `olivercode {command} --schedule`"))


REMOVED_JOBS = tuple("com.olivercode." + name for name in ("city", "workmap", "idle-sessions", "review", "gap-sweep", "burndown", "sweep", "lessons", "fleet-sync", "issues-page"))


def close_fleet_sync_items() -> list[int]:
    """Mark each open owner item the removed fleet-sync command queued as done, with the reason. Returns the ids it closed."""
    from lib import cmd_owner
    closed = [i["id"] for i in cmd_owner.items() if i["status"] == "open" and i.get("session") == "fleet-sync"]
    for item_id in closed:
        cmd_owner.close(item_id, "fleet-sync was removed, so nothing brings this repo level any more")
    if closed:
        print(f"  [QUEUE] closed {len(closed)} owner item(s) from the removed fleet-sync command")
    return closed


def _defined_labels() -> list[str]:
    """The labels of the jobs this code creates."""
    from lib import cmd_boardsweep, cmd_ghreplay, cmd_version, maintain
    return [m.LABEL for m in (cmd_boardsweep, cmd_ghreplay, cmd_version, maintain)]


def _checkout_job_labels(oc_root: Path, folder: Path) -> list[str]:
    """The labels of com.olivercode.* plists in folder whose command runs this checkout's scripts/olivercode."""
    launchers = {str(oc_root / "scripts" / "olivercode"), str(oc_root.resolve() / "scripts" / "olivercode")}
    found = []
    for plist in sorted(folder.glob("com.olivercode.*.plist")) if folder.is_dir() else []:
        try:
            args = plistlib.loads(plist.read_bytes()).get("ProgramArguments", [])
        except (OSError, ValueError):
            continue
        if launchers & {str(a) for a in args}:
            found.append(plist.name[:-len(".plist")])
    return found


def _boot_out(folder: Path, labels, run) -> list[str]:
    gone = []
    for label in dict.fromkeys(labels):
        plist = folder / f"{label}.plist"
        if not plist.is_file():
            continue
        run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        plist.unlink(missing_ok=True)
        print(f"  [JOB] removed {label}")
        gone.append(label)
    return gone


def remove_jobs(oc_root: Path, home: Path | None = None, run=subprocess.run, stale_only: bool = False) -> list[str]:
    """Boot out and delete every com.olivercode.* launchd job this checkout can create, and any other com.olivercode.* plist
    whose command runs this checkout's scripts/olivercode (a job from a newer or older version). Returns the labels it removed (#1272).
    With stale_only, a job this code defines stays and only the others go, which is what install does (#1284).
    Cron and systemd entries are never written by this code, so there is nothing to remove off macOS."""
    if not launchd.supported():
        return []
    folder = launchd.agents_dir(home)
    defined = _defined_labels()
    labels = ([] if stale_only else defined) + list(REMOVED_JOBS) + _checkout_job_labels(oc_root, folder)
    return _boot_out(folder, [label for label in labels if not (stale_only and label in defined)], run)


def _retire_removed_jobs(oc_root: Path) -> None:
    """Remove the jobs of removed commands, and any other job of this checkout the code no longer defines, under the same real-home rule as the scheduled jobs."""
    if _real_home():
        remove_jobs(oc_root, stale_only=True)


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


def _inherit_local_config(oc_root: Path, claude_dir: Path) -> None:
    """A checkout with no olivercode.local.json copies the one from the checkout ~/.claude/CLAUDE.md links to, when that is another checkout (#1282).
    Runs before the links move and before anything reads the config. An existing file is never overwritten."""
    dest = local_path()
    link = claude_dir / "CLAUDE.md"
    if str(dest) == os.devnull or dest.is_file() or not link.is_symlink():
        return
    prior = Path(os.path.realpath(link)).parent
    source = prior / "olivercode.local.json"
    if prior == oc_root.resolve() or not source.is_file():
        return
    shutil.copyfile(source, dest)
    print(f"  [COPIED] olivercode.local.json from {prior}")


def _checkout_of(root: Path, name: str) -> Path | None:
    """The main checkout under repoRoot whose GitHub origin is the repo `name`: where a repoPaths entry points once its folder has moved (#1295)."""
    for path in sorted(placement.checkouts(root)):
        slug = repo_state.origin(path)
        if slug and slug.split("/")[1].lower() == name.lower() and not placement.is_worktree(path):
            return path
    return None


def _converge_local_config() -> list[str]:
    """Bring olivercode.local.json in line with this version (#1295). A key the version does not read is removed, a repoPaths
    entry whose folder is gone points at the checkout of that repo under repoRoot or is removed, and a list names each repo once.
    The file is copied to the backups folder before the first change. Returns one line per change, or none when nothing changed."""
    path = local_path()
    if str(path) == os.devnull or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"[FAIL] {path} is not a JSON object, so it was left as it is ({exc})"]
    if not isinstance(data, dict):
        return [f"[FAIL] {path} is not a JSON object, so it was left as it is"]
    lines = []
    for key in [k for k in data if k not in DEFAULTS]:
        del data[key]
        lines.append(f"[REMOVED] {key} in olivercode.local.json: this version reads no such key")
    paths = data.get("repoPaths")
    if isinstance(paths, dict):
        root = placement.config().root
        for name, value in list(paths.items()):
            if isinstance(value, str) and Path(value).expanduser().is_dir():
                continue
            moved = _checkout_of(root, name)
            if moved:
                paths[name] = str(moved)
                lines.append(f"[MOVED] repoPaths.{name} now points at {moved}")
            else:
                del paths[name]
                lines.append(f"[REMOVED] repoPaths.{name}: no folder at {value} and no checkout of {name} under {root}")
    for key, value in list(data.items()):
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            continue
        seen, kept = set(), []
        for item in value:
            if item.lower() not in seen:
                seen.add(item.lower())
                kept.append(item)
        if len(kept) < len(value):
            data[key] = kept
            lines.append(f"[DEDUPED] {key}: named more than once, now listed once each ({len(value) - len(kept)} repeat(s) dropped)")
    if not lines:
        return []
    backups = failure_log.home() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup = _unused(backups / f"{path.name}.{stamp}", ".")
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return [*lines, f"previous olivercode.local.json kept at {backup}"]


def board_config(path: Path) -> dict | None:
    """The repo's own board config, or None. A config that is absent, still the example's, or names another owner's repo counts as
    absent, so backlog-setup writes this repo's own (#1013). A repo with no origin remote has nothing to compare, so its config stands."""
    from lib import backlog_setup
    config = backlog_setup.load_config(backlog_setup.config_path(path))
    slug = backlog_setup.origin_owner_name(path)
    if config is None or (slug is not None and f"{config['repoOwner']}/{config['repoName']}".lower() != f"{slug[0]}/{slug[1]}".lower()):
        return None
    return config


def board_step(repos: list[tuple[str, Path]]) -> str:
    """Install's board step (#994). With gh signed in and holding the project scope, it runs `backlog-setup --apply` for each repo whose
    backlog config is absent, still the example's or another owner's (#1013), names that config in the repo's CLAUDE.md and prints the board
    URL. A repo with its own valid config is left alone. Returns the line that stopped the step before any board, or "" when it ran."""
    from lib import backlog_setup
    from lib.cmd_fleet import command_backlog_setup
    from lib.health_checks import gh_ready
    problem = gh_ready()
    if problem:
        print(problem)
        return problem
    for name, path in repos:
        try:
            if board_config(path) is not None:
                continue
            if command_backlog_setup([str(path), "--apply"]) != 0:
                print(f"{name}: backlog-setup did not finish. Fix the cause, then run `olivercode backlog-setup {path} --apply`")
                continue
            config = board_config(path)
        except backlog_setup.SetupError as error:
            print(f"{name}: {error}")
            continue
        rel = backlog_setup.config_path(path).relative_to(path)
        claude = path / "CLAUDE.md"
        if claude.is_file() and "backlog-config.json" not in claude.read_text(encoding="utf-8", errors="ignore"):
            clean = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--", "CLAUDE.md"], capture_output=True, text=True).stdout.strip() == ""
            claude.write_text(claude.read_text(encoding="utf-8", errors="ignore") + f"\nBacklog config: `{rel}` names this repo's board.\n", encoding="utf-8")
            if clean:  # commit the line by explicit path so it does not sit as a stray change (#1035)
                subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "Name the backlog config in CLAUDE.md (#1035)", "--", "CLAUDE.md"], capture_output=True)
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
    from lib.cli import MIN_PYTHON, MIN_PYTHON_TEXT, PYTHON_FIX, gh_problem
    if sys.version_info[:2] < MIN_PYTHON:
        print(f"  [FAIL] Python is {sys.version_info[0]}.{sys.version_info[1]} and OliverCode needs {MIN_PYTHON_TEXT} or newer: {PYTHON_FIX}")
        return 1
    old_gh = gh_problem()
    if old_gh:
        print(f"  [FAIL] {old_gh}")
        return 1
    claude_dir = _claude_dir()
    skills_dir = claude_dir / "skills"
    _inherit_local_config(oc_root, claude_dir)
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
            backup = _unused(target.with_name(target.name + BACKUP_SUFFIX), ".")
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

    # DESIGN.md is read on visual work only, so CLAUDE.md does not import it.
    for name, source in (("VOICE.md", voice_file(oc_root)), ("DESIGN.md", design_file(oc_root))):
        print(f"  [{_link(claude_dir / name, source, keep_own=True).upper()}] ~/.claude/{name}")

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
    # The local file holds only the keys this version reads, each repo once, and repo paths that exist (#1295).
    for line in _converge_local_config():
        print(f"  {line}")
    city_added = _city_shortcut(oc_root, claude_dir)
    expected = {k: oc_root / rel for k, rel in RULE_LINKS.items()}
    expected.update({f"skills/{name}": source for name, source in wanted.items()})
    _write_record(claude_dir, {k: os.readlink(claude_dir / k) for k, src in expected.items()
                               if (claude_dir / k).is_symlink() and (claude_dir / k).resolve() == src.resolve()}, city_added)

    broken_settings = False
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

    _schedule_jobs()
    _retire_removed_jobs(oc_root)
    close_fleet_sync_items()

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
    print(OWNER_STEPS)
    print()
    if owner_terminal():
        board_step([("OliverCode", OC_ROOT)])
    else:
        print("Board step skipped here. Run `olivercode install` in your own terminal, or `olivercode backlog-setup DIR --apply` for each repo.")
    print(closing_lines(oc_root))
    if first_install:
        print()
        print(INTRODUCTION)
    return 1 if broken or broken_settings else 0


def _trash_dir() -> Path:
    """The macOS Trash of the real home, resolved at call time so a test that sets HOME gets its own."""
    return Path.home() / ".Trash"


def _trash(path: Path) -> Path:
    """Move path into the Trash under its own name, numbered when that name is taken, and return where it landed."""
    trash = _trash_dir()
    trash.mkdir(exist_ok=True)
    dest = _unused(trash / path.name, " ")
    shutil.move(str(path), dest)
    return dest


def _unset_hooks(repos: list[tuple[str, Path]]) -> tuple[list[str], bool]:
    """Unset core.hooksPath in each repo where it still names OliverCode's `.githooks`, the value sync-hooks sets.
    Any other value is the owner's and stays. Returns the lines to print and whether a unset failed."""
    lines, failed = [], False
    for name, repo in repos:
        value = subprocess.run(["git", "-C", str(repo), "config", "--get", "core.hooksPath"], capture_output=True, text=True).stdout.strip()
        ours = {".githooks", "./.githooks", str(repo / ".githooks"), str((repo / ".githooks").resolve())}
        if not value:
            lines.append(f"  [ABSENT] {name}: core.hooksPath")
        elif value not in ours:
            lines.append(f"  [KEPT] {name}: core.hooksPath is {value}, which is not OliverCode's")
        elif subprocess.run(["git", "-C", str(repo), "config", "--unset", "core.hooksPath"], capture_output=True).returncode:
            lines.append(f"  [FAIL] {name}: core.hooksPath could not be unset; run git -C {repo} config --unset core.hooksPath")
            failed = True
        else:
            lines.append(f"  [OK] {name}: core.hooksPath unset")
    return lines, failed


def command_uninstall(oc_root: Path, run=subprocess.run) -> int:
    """Undo `install`: remove what it wrote in ~/.claude and nothing else, then move the OliverCode home to the Trash.

    A link is removed when it points into this checkout, or when it dangles and an
    OliverCode install wrote it (a checkout that moved), by the install record or, for an
    older install, by corroboration (see _dangling_from_install). Every other link stays,
    and so does a link into another live checkout. The install record goes too.
    The newest `<name>.pre-olivercode` backup install made is moved back once its path is
    free, and any older one is listed. The hook entries come out of settings.json by the
    same rule install uses to replace them, and every other key stays. Idempotent.

    `core.hooksPath` is unset in this checkout and each private repo where it names `.githooks`,
    the value sync-hooks set; a value the owner set elsewhere stays. The home folder (run log, City,
    owner queue, decision ledger) goes last, to the Trash, so it can still be restored.
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
        result = _claude_settings.remove(claude_dir / "settings.json", oc_root)
        print(f"  [{result.upper()}] Claude Code hooks in ~/.claude/settings.json")
    except ValueError as exc:
        print(f"  [FAIL] ~/.claude/settings.json could not be read ({exc}); left as it is, hooks not removed")
        broken_settings = True

    if _record_city(claude_dir):
        for name in (CITY_SHORTCUT, CITY_SHORTCUT_WEBLOC):
            shortcut = _desktop() / name
            if shortcut.is_symlink() or shortcut.exists():
                shortcut.unlink()
                print(f"  [REMOVED] ~/Desktop/{name}")
            else:
                print(f"  [ABSENT] ~/Desktop/{name}")

    jobs = remove_jobs(oc_root, run=run)
    if not jobs:
        print("  [ABSENT] launchd jobs")

    for line in _queue_shim.uninstall_launcher(oc_root):
        print(line)

    hook_lines, broken_hooks = _unset_hooks([("OliverCode", oc_root)] + list(private_repos().items()))
    for line in hook_lines:
        print(line)

    leftovers = [b for name in RULE_LINKS for b in _backups(claude_dir / name)]
    leftovers += _backups(_queue_shim.launcher_path())
    if skills_dir.is_dir():
        leftovers += sorted(b for b in skills_dir.iterdir() if BACKUP_SUFFIX in b.name)
    (claude_dir / INSTALL_RECORD).unlink(missing_ok=True)
    print()
    if leftovers:
        print("Older backups left in place. An earlier install made each one, or something")
        print("now sits at its original path:")
        for b in leftovers:
            print(f"  {b}")
        print()
    if (claude_dir / f"skills{BACKUP_SUFFIX}").exists():
        print(f"~/.claude/skills{BACKUP_SUFFIX} is your own copy from docs/SETUP.md Step 2; uninstall leaves it.")
        print()
    print(f"Uninstall finished: {len(jobs)} scheduled job(s) removed.")
    home = failure_log.home_path()
    broken_home = False
    if home.is_symlink() or home.exists():
        try:
            trashed = _trash(home)
            print(f"OliverCode home moved to the Trash: {trashed}")
        except OSError as exc:
            print(f"  [FAIL] {home} could not be moved to the Trash ({exc}); left as it is")
            broken_home = True
    else:
        print(f"  [ABSENT] OliverCode home {home}")
    return 1 if broken_settings or broken_hooks or broken_home else 0
