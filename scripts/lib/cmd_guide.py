"""`olivercode guide`: how work runs, the first steps and every command grouped by the job it does, one plain line each, in the order of the README table (#985).

`olivercode guide NAME` says what one command, gate, guard, scheduled job or skill does and where it lives, read from the launcher's command table, docs/GATES.md,
the hooks' own docstrings and the skills' own descriptions, so it cannot drift from them."""

from __future__ import annotations

import re
from pathlib import Path

from lib.cli import COMMANDS

# How work runs, printed first (#972). cmd_install's introduction and the first install's closing text quote these lines.
HOW_WORK_RUNS = (
    "You work in Claude Code normally: exploration, strategic conversation, planning, debugging and paired coding remain interactive.",
    "A chat never builds a board story by hand. For unattended execution today, explicitly delegated work is represented by a story on the repo's board; the owner may need to create or choose that story before it can run.",
    "The current queue entry points, `olivercode dispatch N` and `olivercode drain REPO`, start isolated Claude Code worktrees, run validation and safely land or report blocked work.",
    "`olivercode status` and City show current queue/run state; the fuller owner-facing supervision experience is the target described below.",
)

THREAD_LINE = "The thread that started a run is the one to steer it. `olivercode status` answers status from any thread or terminal at no token cost."

# The owner-facing architecture, printed after how work runs.
ARCHITECTURE = (
    "Front door — give an outcome, context and priorities; ordinary interactive Claude Code stays interactive.",
    "Autonomous orchestration — understand, plan, decompose when useful, route, prioritize and coordinate work.",
    "Execution — manage isolated Claude Code sessions, parallelism, resumption and routine recovery.",
    "Quality and delivery — validate proportionally to risk, repair failures, review when warranted, integrate safely and clean up.",
    "Supervision — monitor truthful progress, detect stalls, notify on meaningful changes and ask for decisions only when needed.",
)

# The habits that keep OliverCode cheap, printed by the guide and by the first install's introduction, one line each (#991).
USING_IT_WELL = (
    "Use interactive Claude Code for thinking and collaboration; delegate explicitly when you want OliverCode to take responsibility for execution.",
    "Describe the outcome, constraints and what done looks like; OliverCode should handle the planning and task mechanics.",
    "Let OliverCode determine scope, split work and identify dependencies when doing so improves the result.",
    "Use `olivercode status` to see progress, blockers, completed work and decisions that need you.",
    "Keep owner decisions for genuine trade-offs, permissions, production actions and ambiguous requirements.",
    "Use the current `olivercode dispatch N` and `olivercode drain REPO` entry points for queued execution until the owner front door is fully implemented.",
)

# An example of one story from the first thread to the landed commit, printed after how it works.
EXAMPLE = (
    "1. You tell Claude Code: \"The export button times out on large reports.\" You talk it through in chat; nothing is queued.",
    "2. You decide to hand it over. File the story on the repo's board and note its number, say 42.",
    "3. olivercode dispatch 42: one headless builder claims the story, builds in its own worktree, runs the repo's validation and lands the commit.",
    "4. olivercode status shows it building, then landed. A step only you can take appears in olivercode owner list.",
    "5. When it lands you get the commit, the checks run and the cost in the story comment. If it stops, the comment says why and the card is back on Ready.",
)

# City, the status page published as an artifact, and how it reaches the phone (#999).
PHONE_STEPS = (
    "Install the Claude app on your phone.",
    "Sign in to the same account as the desktop app.",
    "Open the pinned OliverCode City artifact.",
    "Turn on Remote Control for desktop sessions in the desktop app's settings, so you can steer Claude Code from the phone.",
)


def city_url() -> str:
    """The saved City artifact URL, or "" before City is published."""
    from lib.local_config import setting
    return str(setting("cityArtifact") or "")


# The commands by what the owner wants to do. Every command the launcher lists appears once, except the fleet commands #1286 removes.
COMMAND_SETS = (
    ("Install and keep things up to date", "install · uninstall · update · bootstrap · sync-hooks"),
    ("Check and maintain your setup", "health · maintain · limits · place · clean"),
    ("Build and deliver work", "run · dispatch · drain · watch · land · wip · validated · queue · worktree"),
    ("Manage stories and boards", "backlog-setup · board groom · board sync · gh-limit · gated"),
    ("Keep track of work", "status · status digest · owner · decisions"),
    ("Releases and documentation", "version-cut · docs-check · commit-check · guide"),
)
WHEN_TO_USE = (
    ("Working through an idea", "Claude Code"),
    ("Planning or debugging together", "Claude Code"),
    ("Handing off a task", "`dispatch`"),
    ("Running a repo's queue", "`drain`"),
    ("Checking progress", "`status`"),
    ("Finding decisions or blockers", "`owner list`"),
)
JOBS = {"board-sweep": "board sync", "maintain": "maintain",
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


def plain_guide(oc_root: Path) -> list[str]:
    """The guide, short enough to read in under a minute (#1177). The long parts live behind `olivercode guide city`, `guide skills` and `guide design`."""
    from lib import repo_profiles
    try:
        count = len(repo_profiles.load_repo_profiles(oc_root)[0])
    except (OSError, ValueError):
        count = 0
    out = ["OliverCode", "",
           "OliverCode lets you hand Claude Code work to complete on its own. You keep working normally, and OliverCode runs delegated work, checks it and gets it across the finish line.", "",
           "How work runs"] + [f"  {sentence}" for sentence in HOW_WORK_RUNS] + [f"  {THREAD_LINE}", "",
           "How the work is split"] + [f"  {part}" for part in ARCHITECTURE] + ["",
           "Getting started",
           f"  {count} project{'' if count == 1 else 's'} connected." if count else '  No projects are connected yet. Say "Set up OliverCode" in Claude.',
           "  Run `olivercode health` to check that everything is working.",
           "  To hand off work, choose a story and run `olivercode dispatch 42`, or run `olivercode drain REPO` to work through a repo's queue.", "",
           "How it works"]
    out += [f"  {n}. {step}" for n, step in enumerate((
        "Work through an idea with Claude Code.", "When you are ready to hand it off, put it on your repo's board.", "Run `olivercode dispatch 42`.",
        "OliverCode builds it in its own workspace, runs the checks and lands it if everything passes.",
        "Check `olivercode status` to see how it went. If something needs you, OliverCode says so."), 1)]
    out += ["", "An example"] + [f"  {line}" for line in EXAMPLE] + ["", "Using it well"] + [f"  {habit}" for habit in USING_IT_WELL]
    out += ["", "What to use when"] + [f"  {task:<32} {tool}" for task, tool in WHEN_TO_USE] + ["", "Commands"]
    for title, cmds in COMMAND_SETS:
        out += [f"  {title}", f"    {cmds}", ""]
    out += ["Your projects, your rules",
            "  OliverCode uses your repo's rules, validation and permissions. You stay in control of approvals, sensitive actions and anything that needs your judgment.", "",
            "City",
            "  City gives you a live view of work, progress and anything waiting on you. Set it up in Claude Desktop to use it there and from your phone.", "",
            "Run `olivercode guide NAME` for a closer look at any command or skill. `guide city`, `guide skills` and `guide design` cover those topics."]
    return out


def _city_topic(oc_root: Path) -> list[str]:
    url = city_url()
    return ["OliverCode City", "", f"  {url}" if url else "  Not set up in the Claude desktop app. Open it and say \"Set up OliverCode City\" to finish, or \"Skip OliverCode City\" to stop the reminder.", "",
            "To check in from your phone"] + [f"  {n}. {step}" for n, step in enumerate(PHONE_STEPS, 1)]


def _skills_topic(oc_root: Path) -> list[str]:
    out = ["Skills", "", "Say the phrase to Claude Code and the skill loads.", ""]
    for skill, phrases in skill_triggers(oc_root):
        out += [f"  {skill}", f"      {phrases}"]
    return out


def _design_topic(oc_root: Path) -> list[str]:
    return ["Your design file", "", "  Set designFile in olivercode.local.json to your own path, then run `olivercode install` to link it as ~/.claude/DESIGN.md."]


TOPICS = {"city": _city_topic, "skills": _skills_topic, "design": _design_topic}


def command_guide(oc_root: Path, name: str | None = None) -> int:
    if name:
        topic = name.lower().removeprefix("olivercode ").strip()
        if topic in TOPICS:
            print("\n".join(TOPICS[topic](oc_root)))
            return 0
        found = explain(oc_root, name)
        if name.lower().removeprefix("olivercode ").strip() == "status":
            found.append("Status steps\n" + "\n".join(f"  {step}" for step in status_steps(oc_root)))
        if not found:
            print(f"Error: nothing named '{name}' is a command, gate, guard, job or skill. Run `olivercode guide` for the list.")
            return 1
        print("\n\n".join(found))
        return 0
    for line in plain_guide(oc_root):
        print(line)
    return 0
