# .claude-optimization/ — Claude Standalone Operating System

> Claude's self-contained memory/state system for OliverCode. No external agent framework dependency.
> Loaded by vault root CLAUDE.md on session start. Skills moved out to the top-level
> `OliverCode/skills/` directory (one flat home for every non-personal skill) — see
> `docs/skills-placement.md`.

| Directory | Purpose | Tracked? |
|-----------|---------|----------|
| `memory/` | User profile + durable facts | No (personal, gitignored) |
| `state/` | Current optimization targets, decision log, next actions | No (personal, gitignored) |

On a fresh clone only this README exists; `memory/` and `state/` are created locally per user.

---

## How Claude Uses This

1. **Session start:** Read CLAUDE.md → loads `.claude-optimization/memory/USER.md` + `state/current_state.md`
2. **Domain encounter:** Load the relevant skill from `../skills/<name>/SKILL.md` (see `../skills/INDEX.md`)
3. **State updates:** Update `state/current_state.md` after work (decisions + status changes go here)

---

> Created: 2026-06-12 | Last updated: 2026-07-02
