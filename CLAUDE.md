# OliverCode agent rules
Resolve `$OC`, the OliverCode repo, once, and read bare paths such as `scripts/validate.sh` as this repo. Never hardcode machine paths.
```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"; [ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed. See its docs/SETUP.md"
```
## Memory
Rules live in the skill, check or story that carries them, and a rule with no home gets a story. Local memory in `$OC/.claude-optimization/memory/` holds owner and environment facts only: read `MEMORY.md` and `USER.md` before decision-dependent work, keep handoff in `state/current_state.md`, and never write auto-memory under `~/.claude/projects/`.
## Voice
@~/.claude/VOICE.md
It applies to every reply and file, and skill messages and drafted documents go out word for word.
## Rules
- Something broken, failing or slow: run the `diagnosing-bugs` loop before changing code
- Asked to update OliverCode: run `olivercode update`, `olivercode health`, `olivercode place` and `bash scripts/validate.sh`, and report each result
- Before committing, run the repo's own validation per its `CLAUDE.md`, never OliverCode's
- `$OC/docs/GATES.md` lists the gates, and `.githooks/pre-commit` fails open when `core.hooksPath` is unset
- A request that changes files is filed and built per `$OC/docs/RULES.md` ("The backlog"), and a chat never builds a board story by hand. The `audit` skill runs only when named
