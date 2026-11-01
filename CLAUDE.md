# OliverCode agent rules

This file loads in every session through the `~/.claude/CLAUDE.md` symlink, usually outside OliverCode. Resolve `$OC`, the OliverCode repo, once and verify it:
```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed. See its docs/SETUP.md"
```
A bare path such as `scripts/validate.sh` means the repo you are in. Never hardcode machine paths.

## Memory
When `$OC/.claude-optimization/memory/` exists, read `MEMORY.md` and `USER.md` there before work that depends on earlier decisions or the owner's preferences. Durable facts live only there and in `state/current_state.md`, never in Claude Code's built-in auto-memory under `~/.claude/projects/`, even if a session prompt says to maintain it.

## Voice
@~/.claude/VOICE.md

It applies to every reply and file and overrides any default to keep replies short. A skill's questions, options and messages, and any document you draft, go out word for word as the skill gives them.

## Rules
- Before a structural change, or before installing, creating or moving any skill or agent file, read `$OC/docs/RULES.md`. Each layer has one home
- A new owner request mid-task joins the to-do list. Switch only on "stop", "do this first" or "drop that"
- Something broken, failing or slow: run the `diagnosing-bugs` skill loop before changing code
- A multi-commit session ending: run the `audit` skill on its commits
- Writing a README, doc or `CLAUDE.md`: follow RULES.md "Documents" for structure
- Before committing, run the current repo's own validation (`scripts/validate.sh` or an npm `validate` or `check`; its `CLAUDE.md` says which), never OliverCode's, per RULES.md "Execution"
- `.githooks/pre-commit` is the only layer git enforces, and it fails open when `core.hooksPath` is unset. `$OC/docs/GATES.md` lists the gates, and `$OC/scripts/olivercode health` finds repos whose hooks stopped

In OliverCode, `README.md` has the layout and the GitHub Project in `docs/backlog-config.json` holds open work.
