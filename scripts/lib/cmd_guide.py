"""`olivercode guide`: how work runs, the first steps and every command grouped by the job it does, one plain line each, in the order of the README table (#985).

`olivercode guide NAME` says what one command, gate, guard, scheduled job or skill does and where it lives, read from the launcher's command table, docs/GATES.md,
the hooks' own docstrings and the skills' own descriptions, so it cannot drift from them."""

from __future__ import annotations

import re
from pathlib import Path

from lib.cli import COMMANDS

# How work runs, in the order the guide and the README "How work runs" section both print it (#972).
HOW_WORK_RUNS = (
    "You work in one thread, and you say what you want. Each request becomes a story on the repo's board.",
    "`olivercode dispatch N` or `olivercode drain REPO` builds a story in one fresh headless Claude session, in its own worktree. The builder commits and stops, and the runner validates the commit, lands it on main, logs the story and closes it.",
    "A chat never builds a board story by hand: the runner builds it through `olivercode dispatch N` or `olivercode drain REPO`.",
    "`olivercode status` shows what is open.",
)

THREAD_LINE = "The thread that started a run is the one to steer it. `olivercode status` answers status from any thread or terminal at no token cost."

# The habits that keep OliverCode cheap, printed after the first steps by the guide and the first install's introduction, one line each (#991).
USING_IT_WELL = (
    "Work in one thread per topic, and start a fresh one when it grows long.",
    "Never ask a thread for status, open the status page or run `olivercode status`.",
    "Say what you want once and let the runner build it.",
    "Keep a story small and name its files.",
    "Never start a builder in a chat: `olivercode dispatch N` builds a board story without one.",
    "A long thread costs more on every message, because all of it is re-read.",
)


# The README "Commands" table: each job and the commands under it, each with one plain line. tests/test_guide.py holds the README to the same rows.
GROUPS = (
    ("Install and update", (
        ("install", "Link OliverCode's rules, skills and hooks into Claude Code"),
        ("uninstall", "Remove those links and restore what install replaced"),
        ("update", "Pull the newest OliverCode and reinstall it"),
        ("bootstrap", "Add OliverCode's standard files to a repo"),
        ("sync-hooks", "Bring every repo's commit gates up to date"),
        ("place", "Check that every repo and worktree lives in its proper folder"),
        ("clean", "Remove finished worktrees"),
        ("worktree", "Set up a story's own worktree so its first commit passes"),
        ("commit-check", "Test a commit message against the gates before committing"),
    )),
    ("Check a machine or a repo", (
        ("health", "Check that this machine is set up correctly"),
        ("status", "Show how many stories are open and how fast they close"),
        ("status digest", "Write the one-page summary a new thread starts from"),
        ("conform", "Check repos against the shared standard"),
        ("maintain", "Repair what is safe to repair on this machine"),
        ("limits", "Check the size of the repo against its ceiling"),
    )),
    ("Run and land work", (
        ("run", "Run one task in a fresh headless Claude session and validate it"),
        ("dispatch", "Build one story in its own session and land it"),
        ("drain", "Build every open story in a repo, one after another"),
        ("land", "Put a finished story on main"),
        ("wip", "Save uncommitted work without touching the working tree"),
        ("validated", "Record or check that a commit passed full validation"),
        ("queue", "Take a turn in the validation queue"),
    )),
    ("Version and docs", (
        ("version-cut", "Cut a version from what landed on main"),
        ("docs-check", "Check that the docs match the commands, gates and skills"),
    )),
    ("Backlog and boards", (
        ("backlog-setup", "Set up or repair a repo's board"),
        ("board groom", "Fix drifted cards and fill in missing fields"),
        ("board sync", "Move closed stories to Complete and add open stories with no card"),
        ("story", "Hold a story request until GitHub has room to file it"),
        ("candidates", "Keep ideas for stories until the owner picks them"),
        ("gh-limit", "Show or lift the shared GitHub rate-limit hold"),
        ("gated", "Run a scheduled job's command only when a check finds work"),
    )),
    ("Owner and decisions", (
        ("owner", "Keep the steps only the owner can take"),
        ("decisions", "Keep the owner's decisions in their own words"),
    )),
    ("Learning", (
        ("lesson", "Record a mistake and the rule that prevents it"),
    )),
    ("Fleet and policy", (
        ("discover", "Find the git repos on this machine and register them"),
        ("init-fleet", "Create your private repo for fleet settings"),
        ("fleet-sync", "Bring each repo level with its remote"),
        ("policy", "Write the permission policy for a repo"),
    )),
    ("Orientation", (
        ("guide", "Say what everything does, or what one command, gate, guard, job or skill does"),
    )),
)
JOBS = {"board-sweep": "board sync", "fleet-sync": "fleet-sync", "maintain": "maintain",
        "gh-limit": "gh-limit", "version-cut": "version-cut"}  # the scheduled jobs and the command that installs each, as the README names them


def skill_triggers(oc_root: Path) -> list[tuple[str, str]]:
    """Each (skill, what it does and the phrases that load it) pair from the skills' own descriptions, sorted by name."""
    rows = []
    for md in sorted((oc_root / "skills").glob("*/SKILL.md")):
        m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|^---)", md.read_text(encoding="utf-8"), re.S | re.M)
        if m:
            text = " ".join(m.group(1).strip().lstrip(">|-").strip().strip("\"'").split())
            sentences = [s.strip().rstrip(".") + "." for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
            trigger = next((s for s in sentences[1:] if s.lower().startswith(("trigger", "use when", "use it when"))), "")
            rows.append((md.parent.name, " ".join(filter(None, (sentences[0] if sentences else "", trigger)))))
    return rows


def _lives(oc_root: Path, name: str) -> str:
    stem = name.split()[0].replace("-", "_")
    for cand in (f"cmd_{stem}.py", f"cmd_{stem.replace('_', '')}.py", f"{stem}.py"):
        if (oc_root / "scripts" / "lib" / cand).is_file():
            return f"scripts/lib/{cand}"
    return "scripts/olivercode"


def _doc_first(path: Path) -> str:
    m = re.match(r'\s*(?:#![^\n]*\n)?\s*"""(.*?)(?:\n\n|""")', path.read_text(encoding="utf-8"), re.S)
    return " ".join(m.group(1).split()) if m else ""


def explain(oc_root: Path, name: str) -> list[str]:
    """What NAME is and where it lives, for each command, gate, guard, job or skill that carries it. Empty when none does."""
    key = name.lower().removeprefix("olivercode ").strip()
    out: list[str] = []
    for cmd, desc in COMMANDS:
        words = cmd.split()
        if words[1] == key.split()[0]:
            out.append(f"Command: {cmd}\n  {desc}\n  Lives in {_lives(oc_root, words[1])}")
            break
    if key in JOBS:
        out.append(f"Scheduled job: `olivercode {JOBS[key]} --schedule` installs it through launchd and `--unschedule` removes it. It starts no model.")
    for skill, text in skill_triggers(oc_root):
        if skill == key:
            out.append(f"Skill: {skill}\n  {text}\n  Lives in skills/{skill}/SKILL.md")
    gates = oc_root / "docs" / "GATES.md"
    if gates.is_file():
        for row in re.findall(r"(?m)^\| ([^|]+?) \| ([^|]+?) \|", gates.read_text(encoding="utf-8")):
            if row[0].lower() == key:
                out.append(f"Gate: {row[0]}\n  Blocks: {row[1]}\n  Lives in docs/GATES.md, and its script in core/hooks/gates/")
                break
    for cand in (f"{key}.py", f"{key.replace('-', '_')}.py", f"{key.replace('-', '_')}_guard.py", f"{key}-guard.py"):
        hook = oc_root / "scripts" / "hooks" / cand
        if hook.is_file() and ("guard" in cand or "guard" in _doc_first(hook).lower() or key.endswith("guard")):
            out.append(f"Guard: {key}\n  {_doc_first(hook)}\n  Lives in scripts/hooks/{cand}")
            break
    return out


def status_steps(oc_root: Path) -> list[str]:
    """How to follow a run from a terminal, at no token cost (#1059). Install's closing lines, the adoption skill and `olivercode guide status` all print these."""
    return [
        "1. Open the Terminal app.",
        "2. Inside a repo folder, run `olivercode status`.",
        f"3. From any folder, run `olivercode status --root {oc_root}` for this OliverCode checkout.",
        "Each check reads GitHub only and costs no model turn, so run it as often as you like.",
    ]


def command_guide(oc_root: Path, name: str | None = None) -> int:
    if name:
        found = explain(oc_root, name)
        if name.lower().removeprefix("olivercode ").strip() == "status":
            found.append("Status steps\n" + "\n".join(f"  {step}" for step in status_steps(oc_root)))
        if not found:
            print(f"Error: nothing named '{name}' is a command, gate, guard, job or skill. Run `olivercode guide` for the list.")
            return 1
        print("\n\n".join(found))
        return 0
    print("How work runs")
    for sentence in HOW_WORK_RUNS:
        print(f"  {sentence}")
    print(f"  {THREAD_LINE}")
    print("\nFirst steps, in order")
    print("  1. olivercode discover --root <folder holding your repos> --register    add your repos to the fleet")
    print("  2. olivercode health                                                   check this machine")
    print("  3. File your first story: say what you want in Claude Code, then build it with olivercode dispatch N, or olivercode drain REPO")
    print("\nUsing it well")
    for habit in USING_IT_WELL:
        print(f"  {habit}")
    print("\nCommands, by the job they do (olivercode guide NAME says more about one)")
    for job, cmds in GROUPS:
        print(f"\n{job}")
        for cmd, desc in cmds:
            print(f"  {cmd:<16} {desc}")
    print("\nYour design file: set designFile in olivercode.local.json to your own path, then run `olivercode install` to link it as ~/.claude/DESIGN.md")
    print("\nSkills: say the phrase to Claude Code and the skill loads")
    for skill, phrases in skill_triggers(oc_root):
        print(f"  {skill}\n      {phrases}")
    print("\nMore: README.md, docs/SETUP.md (setup and commands)")
    return 0
