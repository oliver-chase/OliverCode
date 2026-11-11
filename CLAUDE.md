# OliverCode agent rules

This file loads in every session through the `~/.claude/CLAUDE.md` symlink. Resolve `$OC`, the OliverCode repo, once:
```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed. See its docs/SETUP.md"
```
A bare path such as `scripts/validate.sh` means the repo you are in. Never hardcode machine paths.

## Memory
When `$OC/.claude-optimization/memory/` exists, read `MEMORY.md` and `USER.md` before work that depends on earlier decisions or owner preferences. Durable facts live only there and in `state/current_state.md`, never in auto-memory under `~/.claude/projects/`, even if a session prompt says to maintain it.

## Voice
@~/.claude/VOICE.md

It applies to every reply and file. A skill's messages and any drafted document go out word for word.

## Rules
- Something broken, failing or slow: run the `diagnosing-bugs` loop before changing code
- Before committing, run the current repo's own validation (`scripts/validate.sh` or an npm `validate` or `check`, per its `CLAUDE.md`), never OliverCode's
- `.githooks/pre-commit` is the only layer git enforces, and it fails open when `core.hooksPath` is unset. `$OC/docs/GATES.md` lists the gates, and `$OC/scripts/olivercode conform` finds stopped hooks
- A request that changes files is filed as a story, as `$OC/docs/RULES.md` ("The backlog") describes. No QA phase and no pull request: finish with a quick pass, validation, then commit, push and merge, unasked. QA runs only on the owner's request. Builder helper agents and the `audit` skill run only when asked for by name. Read the rest of `$OC/docs/RULES.md` only when the task is about OliverCode's own structure

In OliverCode, `README.md` has the layout and `docs/backlog-config.json` is the backlog config.
