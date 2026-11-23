"""Health checks: vault skill links, voice and design copies, placement drift, memory, version, Python and launcher.

`health_topology.py` holds the fleet-location, remote and oversized-file checks, and this file re-exports them. `cmd_health.py` imports these names. Every check returns (passed, failed, skipped) for the launcher's tally.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lib import claude_settings as _claude_settings
from lib import failure_log
from lib.cli import MIN_PYTHON, MIN_PYTHON_TEXT, PYTHON_FIX, gh_problem, python_version
from lib.local_config import claude_dir as _claude_dir
from lib.local_config import design_file, fleet_registry_path

from lib.skill_links import broken_links, link_states
from lib.skills_catalog import skill_dirs
from lib.health_topology import _check_fleet_locations, _check_oversized_tracked, _check_remotes_resolve  # noqa: E401,F401


def _check_vault_skill_links(skills_root: Path | None, oc_skills: Path | None = None) -> tuple[int, int, int]:
    """Every skill in this machine's skills folder must be symlinked into ~/.claude/skills/.

    A skill under `oc_skills` (OliverCode's own folder) is left to the placement drift check,
    so one bad link prints one FAIL.

    A skill with no matching symlink is invisible to the Skill tool and nothing says
    why. Walks nested skill folders, so a skill under any family subfolder is
    still found. The folder comes from local_config; a machine
    with none set has nothing to check here.
    """
    print("\nSkill links:")
    if skills_root is None:
        print("  [INFO] no skills folder set for this machine (skillsRoot) — not checked")
        return 0, 0, 0
    target_dir = _claude_dir() / "skills"

    if not skills_root.is_dir():
        print(f"  [WARN] skills folder {skills_root} not found — skipping")
        return 0, 0, 1
    if not target_dir.is_dir():
        print("  [WARN] ~/.claude/skills/ not present — skipping")
        return 0, 0, 1

    non_skill_dirs = {"docs"}
    declared = []
    for dirpath, dirnames, filenames in os.walk(skills_root):
        dirnames[:] = [d for d in dirnames if d not in non_skill_dirs and not d.startswith(".")]
        if "SKILL.md" in filenames:
            declared.append(Path(dirpath))
            dirnames[:] = []
    if oc_skills is not None:
        declared = [d for d in declared if not d.resolve().is_relative_to(oc_skills.resolve())]
    declared.sort()

    if not declared:
        print(f"  [WARN] {skills_root} holds no skill with a SKILL.md — skipping")
        return 0, 0, 1

    passed = failed = 0
    states = link_states({d.name: d for d in declared}, target_dir)
    for skill_dir in declared:
        name = skill_dir.name
        link = target_dir / name
        state = states[name]
        if state == "absent":
            print(f"  [FAIL] {name}: not linked into ~/.claude/skills/ — invisible to the Skill tool")
            failed += 1
        elif state == "broken":
            print(f"  [FAIL] {name}: symlink is broken (points at {link.readlink()})")
            failed += 1
        elif state == "elsewhere":
            print(f"  [FAIL] {name}: linked to {link.resolve()}; expected {skill_dir}")
            failed += 1
        else:
            passed += 1
    if passed and not failed:
        print(f"  [OK] all {passed} skills from skillsRoot linked")
    return passed, failed, 0


def _check_voice_copies(oc_root: Path, skills_dir: Path) -> tuple[int, int, int]:
    """A self-contained suite's docs/VOICE.md must start with this repo's docs/VOICE.md.

    A suite may add its own sections after the shared text, and any edit to the shared
    text fails.

    A suite ships its own copy so it runs without OliverCode, and nothing else notices
    when one copy is edited and the others are not. A suite is found from its skills
    linked into ~/.claude/skills (<suite>/skills/<name>), so no machine path is
    configured anywhere.
    """
    print("\nVoice copies:")
    canonical = oc_root / "docs" / "VOICE.md"
    if not canonical.is_file():
        print("  [FAIL] docs/VOICE.md missing — CLAUDE.md imports it through ~/.claude/VOICE.md")
        return 0, 1, 0
    if not skills_dir.is_dir():
        print("  [INFO] ~/.claude/skills/ not present — not checked")
        return 0, 0, 0
    suites = set()
    all_roots = set()
    for link in skills_dir.iterdir():
        if not (link.is_symlink() and link.exists()):
            continue
        skill = link.resolve()
        root = skill.parent.parent
        if skill.parent.name == "skills" and root != oc_root.resolve():
            all_roots.add(root)
            if (root / "docs" / "VOICE.md").is_file():
                suites.add(root)
    if not suites:
        print("  [INFO] no installed suite ships docs/VOICE.md — not checked")
        return 0, 0, 0
    passed = failed = 0
    text = canonical.read_bytes()
    for root in sorted(suites):
        if (root / "docs" / "VOICE.md").read_bytes().startswith(text):
            print(f"  [OK] {root.name}/docs/VOICE.md keeps the shared text")
            passed += 1
        else:
            print(f"  [FAIL] {root.name}/docs/VOICE.md changes the shared text — copy it from {canonical} and keep its own sections after it")
            failed += 1
    # A repo may follow the shipped DESIGN.md or the owner's own designFile (#995), so either one passes and a repo matching neither fails.
    sources = []
    for candidate in (oc_root / "docs" / "DESIGN.md", design_file(oc_root)):
        if candidate.is_file() and candidate.read_bytes() not in [s.read_bytes() for s in sources]:
            sources.append(candidate)
    if sources:
        for root in sorted(r for r in all_roots if (r / "docs" / "DESIGN.md").is_file()):
            text = (root / "docs" / "DESIGN.md").read_bytes()
            if any(text.startswith(source.read_bytes()) for source in sources):
                print(f"  [OK] {root.name}/docs/DESIGN.md keeps the shared text")
                passed += 1
            else:
                print(f"  [FAIL] {root.name}/docs/DESIGN.md changes the shared text — copy it from {design_file(oc_root)} and keep its own sections after it")
                failed += 1
    return passed, failed, 0


def _check_placement_drift(oc_root: Path) -> tuple[int, int, int]:
    print("\nPlacement drift (docs/RULES.md):")
    passed = 0
    failed = 0
    skipped = 0

    # (a)/(b) Every OliverCode skill must have a live, correctly-targeted symlink at
    # ~/.claude/skills/<name> -- that's the mechanism making it invocable from any repo.
    # ~/.claude/skills/ is a real directory (not one whole-directory symlink) holding a
    # mix of individual symlinks (orchestration + personal) and real, untracked product/
    # GTM and vendor content -- only the symlinked half is checkable from here.
    claude_skills_dir = _claude_dir() / "skills"
    if not claude_skills_dir.is_dir():
        print("  [WARN] ~/.claude/skills/ not present — skipping")
        skipped += 1
    else:
        skills_dir = oc_root / "skills"
        oc_skill_names = [p.name for p in skill_dirs(skills_dir)] if skills_dir.is_dir() else []
        states = link_states({n: skills_dir / n for n in oc_skill_names}, claude_skills_dir)
        installed = [n for n, st in states.items() if st == "ok"]
        missing = [n for n, st in states.items() if st in ("absent", "real")]
        wrong_target = [n for n, st in states.items() if st == "elsewhere"]
        if oc_skill_names and not installed:
            # Zero symlinks resolve into THIS checkout: it isn't the machine's installed
            # OliverCode (fresh clone, fork, or scratch copy). That's a valid state, not
            # drift, because a stranger's fresh clone must report HEALTHY.
            print(f"  [WARN] this checkout is not the machine's installed OliverCode "
                  f"(no ~/.claude/skills/ symlinks point here) — to install, see docs/SETUP.md")
            skipped += 1
        elif missing:
            print(f"  [FAIL] not symlinked at ~/.claude/skills/: {', '.join(missing)}")
            failed += 1
        elif wrong_target:
            print(f"  [FAIL] symlinked but pointing elsewhere: {', '.join(wrong_target)}")
            failed += 1
        elif "broken" not in states.values():
            print(f"  [OK] all {len(oc_skill_names)} OliverCode skills correctly symlinked at ~/.claude/skills/")
            passed += 1

        broken = broken_links(claude_skills_dir)
        if broken:
            print(f"  [FAIL] broken symlinks in ~/.claude/skills/: {', '.join(broken)}")
            failed += 1
        else:
            passed += 1

    return passed, failed, skipped


def _check_activation_links(claude_dir: Path) -> tuple[int, int, int]:
    """Every activation link in ~/.claude must resolve: CLAUDE.md, VOICE.md and each skill link.

    A link that points at a moved or deleted checkout loads nothing and says nothing, so the
    session runs without the rules. Install re-points them, so each failure prints that command.
    A machine where install never ran has no links, which is a skip.
    """
    passed = failed = 0
    links = [claude_dir / "CLAUDE.md", claude_dir / "VOICE.md", claude_dir / "DESIGN.md"]
    skills = claude_dir / "skills"
    if skills.is_dir():
        links += sorted(p for p in skills.iterdir() if p.is_symlink())
    if not any(p.is_symlink() for p in links[:2]):
        print("  [WARN] no activation links in ~/.claude, so install has not run here")
        return 0, 0, 1
    for link in links:
        if not link.is_symlink():
            continue
        if link.exists():
            passed += 1
        else:
            failed += 1
            print(f"  [FAIL] {link} points at {os.readlink(link)}, which does not exist. "
                  f"Run `olivercode install` from the OliverCode checkout to re-point it")
    if not failed:
        print(f"  [OK] all {passed} activation links resolve")
    return passed, failed, 0


MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")


def _check_managed_hooks_only(managed_path: Path = MANAGED_SETTINGS) -> tuple[int, int, int]:
    """Warn when managed settings set `allowManagedHooksOnly` and carry no OliverCode hooks.

    Claude Code then ignores every hook in ~/.claude/settings.json, so the gates stop with no error.
    A user cannot lift the lock, so this is a WARN that names the fix. No managed file, an unreadable
    one or a lock that is off says nothing.
    """
    try:
        managed = json.loads(managed_path.read_text())
    except (OSError, ValueError):
        return 0, 0, 0
    if not isinstance(managed, dict) or managed.get("allowManagedHooksOnly") is not True:
        return 0, 0, 0
    lacking = _claude_settings.missing(managed_path)
    print("\nManaged hooks lock:")
    if not lacking:
        print("  [OK] managed settings lock hooks and carry all OliverCode hooks")
        return 1, 0, 0
    print(f"  [WARN] {managed_path} sets allowManagedHooksOnly, so Claude Code ignores the OliverCode hooks in "
          f"~/.claude/settings.json ({', '.join(lacking)} missing there). Add those hooks to the managed settings, "
          "since a user cannot lift the lock")
    return 0, 0, 1


# The sources a worktree's commit hooks are built from. A worktree builds them from its own branch, so they are older than
# origin/main once main changes any of these after the worktree branched (#902).
GATE_SOURCES = (".githooks", "core/hooks", "scripts/build-hooks.py", "core/templates/project/pre-commit*",
                "core/templates/project/pre-push", "core/templates/project/commit-msg")


def stale_hook(path: Path, base: str = "origin/main") -> str:
    """Why a worktree's commit hooks predate `base`, or "" when they are current or the worktree has no gates (#902)."""
    from lib import repo_gates
    if not repo_gates.has_gates(path):
        return ""
    fork = subprocess.run(["git", "-C", str(path), "merge-base", "HEAD", base], capture_output=True, text=True)
    if fork.returncode or not fork.stdout.strip():
        return ""
    changed = subprocess.run(["git", "-C", str(path), "diff", "--name-only", fork.stdout.strip(), base, "--", *GATE_SOURCES],
                             capture_output=True, text=True)
    if changed.returncode or not changed.stdout.strip():
        return ""
    return f"{changed.stdout.split()[0]} changed on {base} after this worktree branched"


def _check_worktree_hooks() -> tuple[int, int, int]:
    """Fail each linked worktree whose commit hooks predate origin/main, and name it with its fix (#902). A worktree with no gates says nothing."""
    from lib import placement
    stale = [(wt.path, why) for wt in placement.worktrees() if (why := stale_hook(wt.path))]
    print("\nWorktree hooks:")
    if not stale:
        print("  [OK] every worktree's commit hooks are current with origin/main")
        return 1, 0, 0
    for path, why in stale:
        print(f"  [FAIL] {path} runs commit hooks older than origin/main ({why}). Rebase it with "
              f"`git -C \"{path}\" rebase origin/main`, then run `olivercode worktree fix \"{path}\"`. "
              "Once it is merged, `olivercode clean --apply` removes it")
    return 0, len(stale), 0


MEMORY_WORDS = 5000


def _check_memory(oc_root: Path, budget: int = MEMORY_WORDS) -> tuple[int, int, int]:
    """The memory files stay within 5,000 words, and an entry that names a gone path is stale.

    Stale entries are listed and never deleted: the owner decides what to drop.
    """
    import re

    folder = oc_root / ".claude-optimization" / "memory"
    files = sorted(folder.glob("*.md")) if folder.is_dir() else []
    if not files:
        print("  [INFO] no memory files on this machine, so memory is not checked")
        return 0, 0, 0
    passed = failed = skipped = 0
    words = {f.name: len(f.read_text(encoding="utf-8").split()) for f in files}
    total = sum(words.values())
    if budget and total > budget:
        failed += 1
        largest = ", ".join(f"{n} ({w})" for n, w in sorted(words.items(), key=lambda x: -x[1])[:3])
        print(f"  [FAIL] memory holds {total} words, over the {budget} budget by {total - budget}. Largest: {largest}")
    else:
        passed += 1
        print(f"  [OK] memory holds {total} words" + f" of {budget}")
    stale = []
    for f in files:
        for ref in sorted(set(re.findall(r"`([~\w./-]+/[\w./-]+|[\w-]+\.(?:md|py|sh|json))`", f.read_text(encoding="utf-8")))):
            # A ~/ path names a home path whatever the base, so it is expanded before any join.
            candidates = [Path(ref).expanduser()] if ref.startswith("~") else [base / ref for base in (oc_root, Path.home())]
            if not any(c.exists() for c in candidates):
                stale.append(f"{f.name}: {ref}")
    if stale:
        skipped += 1
        print("  [WARN] stale memory entries name a path that is gone from here (nothing was deleted):")
        for line in stale[:10]:
            print(f"         {line}")
    else:
        passed += 1
        print("  [OK] no memory entry names a missing path")
    return passed, failed, skipped


def _check_commits_behind(oc_root: Path) -> tuple[int, int, int]:
    """Print how many commits this checkout is behind upstream/main (origin/main on a clone) and their one-line log.

    Reads only refs already fetched, so health stays offline. A checkout with neither remote ref has nothing to compare.
    """
    for ref in ("upstream/main", "origin/main"):
        done = subprocess.run(["git", "-C", str(oc_root), "log", "--oneline", f"HEAD..{ref}"], capture_output=True, text=True)
        if done.returncode == 0:
            break
    else:
        print("  [INFO] no upstream/main or origin/main fetched, so the commits behind were not counted")
        return 0, 0, 0
    lines = done.stdout.splitlines()
    if not lines:
        print(f"  [OK] level with {ref}")
        return 1, 0, 0
    print(f"  [WARN] {len(lines)} commit(s) behind {ref}. Run `olivercode update`. Newest first:")
    for line in lines[:15]:
        print(f"         {line}")
    return 0, 0, 1


SUITE_STALE_DAYS = 2


def suite_record_path() -> Path:
    """Where the daily job writes the clean-clone suite's record (maintain.check_suite)."""
    return failure_log.home() / "clean-clone-suite.json"


def _check_clean_clone_suite(record: Path | None = None, now: float | None = None) -> tuple[int, int, int]:
    """The clean-clone suite must have passed on a commit within two days (#977). A failed record names its failing modules, and a
    stale one means the daily job has not run. A machine with no record yet is skipped, since the job has not run there."""
    print("\nClean-clone suite:")
    path = record or suite_record_path()
    if not path.is_file():
        print("  [INFO] no clean-clone run recorded yet; the daily job runs it")
        return 0, 0, 1
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f"  [FAIL] {path} does not parse; run `olivercode maintain --fix` to rewrite it")
        return 0, 1, 0
    commit = data.get("commit") or "unknown"
    if data.get("exit"):
        print(f"  [FAIL] the clean-clone suite failed on commit {commit}: {', '.join(data.get('failed') or ['no module was named'])}")
        return 0, 1, 0
    age = ((time.time() if now is None else now) - data.get("at", 0)) / 86400
    if age > SUITE_STALE_DAYS:
        print(f"  [FAIL] the clean-clone suite last ran {age:.1f} days ago on commit {commit}; run `olivercode maintain --fix` or check the daily job")
        return 0, 1, 0
    print(f"  [OK] the clean-clone suite passed on commit {commit}: {data.get('tests', 0)} tests, {age:.1f} days ago")
    return 1, 0, 0


def _check_fleet_repo(dest: Path | None = None) -> tuple[int, int, int]:
    """The fleet folder holds the registry and owner rules, and it must be a git repo (#993). Health only reads: a loose folder fails
    and names the command that makes it a repo."""
    dest = dest or fleet_registry_path().parent
    print("\nFleet repo:")
    if not (dest / "repo-profiles.json").exists():
        print("  [INFO] no fleet folder here yet; `olivercode install` makes one")
        return 0, 0, 1
    if not (dest / ".git").exists():
        print(f"  [FAIL] {dest} is a loose folder, not a git repo; run `git -C {dest} init` and commit its files")
        return 0, 1, 0
    print(f"  [OK] {dest} is a git repo")
    return 1, 0, 0


def _check_python() -> tuple[int, int, int]:
    """The `python3` a shell finds must meet MIN_PYTHON (lib/cli.py).

    The hooks and gates run under that python3. An older one parses some of them and
    fails on others, so a half-working harness looks like a healthy one.
    """
    print("\nPython:")
    exe = shutil.which("python3")
    found = python_version(exe) if exe else None
    if found is None:
        print(f"  [FAIL] python3 not found or not runnable. Need Python {MIN_PYTHON_TEXT} or newer: {PYTHON_FIX}")
        return 0, 1, 0
    if found < MIN_PYTHON:
        print(f"  [FAIL] python3 is {found[0]}.{found[1]} ({exe}), and OliverCode needs {MIN_PYTHON_TEXT} or newer: {PYTHON_FIX}")
        return 0, 1, 0
    print(f"  [OK] python3 is {found[0]}.{found[1]}, at or above the minimum {MIN_PYTHON_TEXT}")
    return 1, 0, 0


def _gh_auth_status() -> subprocess.CompletedProcess:
    return subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=30)


def _check_gh_version(problem=gh_problem) -> tuple[int, int, int]:
    """The `gh` a shell finds must meet MIN_GH, because four commands page the REST API with `--paginate --slurp`."""
    print("\nGitHub CLI version:")
    old = problem()
    if old:
        print(f"  [FAIL] {old}")
        return 0, 1, 0
    print("  [OK] gh is new enough, or not installed (its own check reports that)")
    return 1, 0, 0


def _check_gh_auth(runner=None) -> tuple[int, int, int]:
    """`gh` must be signed in, because the backlog skill and the board checks all run through it.

    Health must exit 0 on a clone with no local context (docs/SETUP.md), so a missing gh and a signed-out gh
    are both warnings. The signed-out row names the fix. `runner` stands in for
    `gh auth status` in tests, so no check here makes a live call.
    """
    print("\nGitHub CLI:")
    try:
        result = (runner or _gh_auth_status)()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  [WARN] gh is not installed or did not answer, so its sign-in was not checked. Install it from https://cli.github.com")
        return 0, 0, 1
    if result.returncode == 0:
        if "project" not in _scopes(result):
            print("  [FAIL] gh is signed in without the project scope, so no board can take a story. Run: gh auth refresh -s project")
            return 0, 1, 0
        print("  [OK] gh is signed in with the repo and project scopes")
        return 1, 0, 0
    print("  [WARN] gh is signed out, so the backlog and board checks cannot reach GitHub. Run: gh auth login")
    return 0, 0, 1


def _scopes(result) -> set[str]:
    """The token scopes `gh auth status` lists. It reads the token's own record, so no GraphQL point is spent (#994)."""
    text = f"{result.stdout or ''}{result.stderr or ''}"
    found = re.search(r"Token scopes:\s*(.+)", text)
    return set(re.findall(r"'([^']+)'", found.group(1))) if found else set()


def gh_ready() -> str:
    """"" when gh is installed, signed in and holds the project scope, else the one line that names the fix (#994)."""
    try:
        result = _gh_auth_status()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "gh is not installed or did not answer. Install it from https://cli.github.com, then run: gh auth login"
    if result.returncode:
        return "gh is not signed in. Run: gh auth login, then gh auth refresh -s project"
    if "project" not in _scopes(result):
        return "gh is signed in without the project scope. Run: gh auth refresh -s project"
    return ""


SLEEP_FIX = ("In System Settings, open Battery or Energy and turn off sleep on power adapter and display sleep (Never), "
             "or run `caffeinate -dimsu` in a terminal before leaving")


def sleep_warning(pmset_text: str) -> str | None:
    """The one plain line naming the fix when `pmset -g` shows a sleep that would stop a session, else None.

    Display sleep and system sleep both count when their timer is above 0 minutes. A system sleep that
    powerd reports as prevented by caffeinate holds the machine awake, so it does not count.
    """
    stops = []
    for line in pmset_text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] not in ("sleep", "displaysleep") or not parts[1].isdigit() or int(parts[1]) == 0:
            continue
        if parts[0] == "sleep" and "caffeinate" in line:
            continue
        stops.append("display sleep" if parts[0] == "displaysleep" else "system sleep")
    if not stops:
        return None
    return f"This Mac would stop work on {' and '.join(stops)}. {SLEEP_FIX}"


def _pmset_text() -> str:
    return subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=15).stdout


def _check_sleep(runner=None, system: str | None = None) -> tuple[int, int, int]:
    """Warn, never fail, when a sleep setting would stop a session. Skips on a host that is not macOS.

    `runner` stands in for `pmset -g` in tests, so no check here reads the live machine.
    """
    print("\nSleep settings:")
    if (system or sys.platform) != "darwin":
        print("  [INFO] not macOS, so sleep settings were not checked")
        return 0, 0, 0
    try:
        text = (runner or _pmset_text)()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  [WARN] pmset did not answer, so sleep settings were not checked")
        return 0, 0, 1
    warning = sleep_warning(text)
    if warning:
        print(f"  [WARN] {warning}")
        return 0, 0, 1
    print("  [OK] no sleep setting would stop work")
    return 1, 0, 0


def _check_launcher(oc_root: Path, launcher: Path | None = None) -> tuple[int, int, int]:
    """A launcher at /usr/local/bin/olivercode (or the path in OLIVERCODE_LAUNCHER) must reach a launcher that exists.

    After the checkout moves, the link or wrapper keeps pointing at the old folder and every
    `olivercode` call dies with a bare "No such file". No launcher there is a skip.
    """
    launcher = launcher or Path(os.environ.get("OLIVERCODE_LAUNCHER") or "/usr/local/bin/olivercode")
    print("\nLauncher:")
    repair = f"ln -sf {oc_root / 'scripts' / 'olivercode'} {launcher}"
    if not launcher.is_symlink() and not launcher.exists():
        print(f"  [INFO] no launcher at {launcher} — not checked")
        return 0, 0, 0
    if launcher.is_symlink():
        target = os.readlink(launcher)
        if launcher.exists():
            print(f"  [OK] {launcher} reaches {launcher.resolve()}")
            return 1, 0, 0
        print(f"  [FAIL] {launcher} points at {target}, which does not exist. Repair it with: {repair}")
        return 0, 1, 0
    import re
    text = launcher.read_text(errors="ignore")
    dead = [p for p in re.findall(r"\"(/[^\"$]+)\"|'(/[^'$]+)'|(?:=|exec \S+ )(/[^\s\"'$]+)", text)
            for p in p if p and not Path(p).exists()]
    if dead:
        print(f"  [FAIL] {launcher} names {dead[0]}, which does not exist. Repair it with: {repair}")
        return 0, 1, 0
    print(f"  [OK] {launcher} reaches an existing launcher")
    return 1, 0, 0
