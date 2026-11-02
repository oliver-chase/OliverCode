# OliverCode agent rules

This file loads in every session through the `~/.claude/CLAUDE.md` symlink. Resolve `$OC`, the OliverCode repo, once:
```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed. See its docs/SETUP.md"
```
A bare path such as `scripts/validate.sh` means the repo you are in. Never hardcode machine paths.

## Memory
When `$OC/.claude-optimization/memory/` exists, read `MEMORY.md` and `USER.md` before work that depends on earlier decisions or owner preferences. Durable facts live only there and in `state/current_state.md`, never in auto-memory under `~/.claude/projects/`.

## Voice
@~/.claude/VOICE.md

It applies to every reply and file and overrides any default to keep replies short. A skill's messages and any drafted document go out word for word.

## Rules
- Before a structural change, or installing, creating or moving a skill or agent file, read `$OC/docs/RULES.md`. Each layer has one home
- Every owner request, however small, is saved as a story with Gherkin criteria under an epic before work starts (`backlog` skill)
- A request mid-task is filed and queued. Switch only on "stop", "do this first" or "drop that"
- Work goes to a helper agent on the smallest model that fits: Haiku for lookups and mechanical edits, Sonnet for building, research and review. The lead checks its result against the files before reporting or committing. A session cannot change its own model, so point to the app's model menu
- Something broken, failing or slow: run the `diagnosing-bugs` loop before changing code
- A multi-commit session ending: run the `audit` skill on its commits
- Writing a README, doc or `CLAUDE.md`: follow RULES.md "Documents"
- Before committing, run the current repo's own validation (`scripts/validate.sh` or an npm `validate` or `check`, per its `CLAUDE.md`), never OliverCode's, per RULES.md "Execution"
- `.githooks/pre-commit` is the only layer git enforces, and it fails open when `core.hooksPath` is unset. `$OC/docs/GATES.md` lists the gates, and `$OC/scripts/olivercode health` finds stopped hooks

In OliverCode, `README.md` has the layout and the Project in `docs/backlog-config.json` holds open work.
