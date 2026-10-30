# Skill Placement Contract — OliverCode

> **Status: active — canonical.** Any agent installing, creating, or moving a skill file
> inside this repo MUST consult this first. OliverCode is orchestration/security/
> optimization only — engineering method skills and the framework's own tooling. Nothing
> else belongs in `skills/`.

## What belongs here

Engineering method skills and the framework's own tooling (debugging, audits, planning, backlog) — real, git-tracked content in `skills/`.
Indexed in `skills/INDEX.md` — the index IS the catalog.

Nothing else. If a skill doesn't fit that description, it doesn't belong in this repo —
full stop, regardless of what it is or where it should actually live instead.

## Adding a new orchestration skill

1. `skills/<name>/SKILL.md` — real content, tracked.
2. Add a row to `skills/INDEX.md` in the same change.
3. Symlink it into the live skills directory: `ln -s <path-to-OliverCode>/skills/<name> ~/.claude/skills/<name>` — this is what makes it invocable from any repo on the machine. All three steps in the same session. An unsymlinked skill is invisible, an un-indexed one is undiscoverable.

## The one project-level pointer

`.claude/skills/olivercode-adoption` is a tracked SYMLINK to `skills/olivercode-adoption`.
It is not a second home — the real content lives in `skills/` like everything else.

It exists to break a chicken-and-egg: the skill that walks someone through installing
OliverCode was only invocable AFTER `olivercode install` had symlinked it into
`~/.claude/skills/`, i.e. after the step it exists to guide. A project-level skill is
available the moment the repo is cloned and opened, before anything is installed.

Do not add a second one without the same justification. Every other skill reaches the user
through `~/.claude/skills/`.

## Hard rules

- **OliverCode stays orchestration-only.** If anything that isn't engineering method or framework tooling shows up inside `skills/`, that's drift — remove it.
- **Every new skill pairs with its `INDEX.md` row and its symlink** in the same session.
- **Never store skills in the vault's note folders**. A skill's one home is a skill directory.
- **Hooks are not skills** but follow the same pattern: canonical templates live in `OliverCode/core/templates/project/` (the single template home). Every fleet repo (and the vault itself) gets its copy via the bootstrap manifest, `core.hooksPath = .githooks`. Public repos use `pre-commit`, private repos (the vault) use the 4-gate private variant.
- **Every `SKILL.md` and `CLAUDE.md`, in this repo or any fleet repo, be checked by the asd-ste100 writing-clarity gate at commit time.** `docs/GOVERNANCE.md`'s coverage table has the gate. It warns on findings so the author sees them without running the skill by hand.
- **Every skill's structure and MCP-tool usage, not just its prose, is held to a token-cost bar.** No monolith `SKILL.md`, no duplicated paragraph, gap-filling automated instead of asked for, MCP calls following the named efficiency patterns — `core/contracts/SKILL_EFFICIENCY_STANDARD.md` is the full rule set. Checked mechanically today only for the personal skills folder, by hand everywhere else.

## When a repo-specific skill must win over a generic one

A generic skill and a repo-specific skill can both plausibly match the same task — verified
directly: a generic email-writing skill and a repo's own approval-gated outreach skill both
matched "draft a cold email sequence." Skill-tool matching is task-phrasing-based and
happens before any repo file has been touched, so the generic skill can fire first even
inside the repo the specific one was built for — this is a real, verified failure mode (see
`docs/BACKLOG.md`'s ACT-3), not a hypothetical.

There is no framework-level fix for the initial mis-fire — nothing currently gives a
repo-specific skill priority over a generic one at match time. The mitigation that does
work: put a **named, explicit** directive in that repo's own `CLAUDE.md` (which auto-loads
for every session in that repo) naming the mandatory skill and the generic one to avoid by
name, inside a section the agent is likely to read early (e.g. "Approval Boundaries").
Verified this catches the agent on first repo-file-touch and causes it to redo the work via
the correct path, even when it already invoked the wrong skill moments earlier — a
harm-reduction correction, not prevention of the initial mis-fire. If your repo has an
approval-gated skill a generic one could shadow, add this directive.

## Drift check

`scripts/olivercode health` flags: any of OliverCode's own skills missing its symlink at
`~/.claude/skills/<name>`, or a symlink there pointing somewhere other than
`OliverCode/skills/<name>`. It also flags, for every fleet repo plus the vault, any hook install state
that would make git run no hooks — `core.hooksPath` unset, pointing at a missing directory,
a hooks directory with no `pre-commit` file, a `pre-commit` that isn't executable, or one
whose content diverges from the template.

The first four of those are fail-OPEN: git skips hooks silently, so a commit carrying
secrets succeeds with no error. Nothing else on the machine detects it. Repair with
`scripts/olivercode sync-hooks`.
