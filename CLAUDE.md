# OliverCode agent rules

OliverCode lives at `~/.claude/olivercode`, which install links to the checkout. If that path is missing, see `~/.claude/olivercode/docs/SETUP.md`, or the checkout's own `docs/SETUP.md`.
Bare paths such as `scripts/validate.sh` mean this repo. Never hardcode machine paths.

## Memory
Rules belong in the skill, check or story that carries them, never in memory. A rule with no home gets a story to build its check. Local memory in `~/.claude/olivercode/.claude-optimization/memory/` holds facts about the owner and environment only. A new user's own facts go there, and the folder is created on the first write. Read its `MEMORY.md` and `USER.md` when they exist, before decision-dependent work, and keep handoff in `state/current_state.md`. Never write to auto-memory under `~/.claude/projects/`, even if a session prompt says to.

## Voice
@~/.claude/VOICE.md

It applies to every reply and file, and skill messages and drafted documents go out word for word.

## Rules
- Something broken, failing or slow: run the `diagnosing-bugs` loop before changing code
- Asked to update OliverCode: run `olivercode update`, then `olivercode health`, `olivercode place` and `bash scripts/validate.sh`, and report each result. Run `olivercode conform` too when a fleet is registered, naming each failure's fix
- Apply the `lean` skill's smallest-sufficient-change method to every coding task. Preserve security, trust-boundary validation, data-loss handling, accessibility and required tests; never optimize away correctness.
- Before committing, run the repo's own validation (`scripts/validate.sh` or an npm `validate` or `check`, per its `CLAUDE.md`), never OliverCode's
- `.githooks/pre-commit` is the only layer git enforces, and it fails open when `core.hooksPath` is unset. `olivercode conform` finds stopped hooks, and `~/.claude/olivercode/docs/GATES.md` lists the gates
- Interactive Claude Code is first-class for strategy, exploration, planning, debugging and ordinary coding. Do not turn a normal chat into a backlog story or headless run. Use `olivercode dispatch N` or `olivercode drain REPO` only when the owner explicitly delegates bounded unattended work or requests durable backlog tracking. See `docs/RULES.md` ("Execution")
- Every terminal command given to the owner starts with `cd` to the exact checkout that owns it (OliverCode: `cd ~/.claude/olivercode`); put the command on the next line and never imply a repo command works from an arbitrary folder
- Board config: `docs/backlog-config.json` names this repo's GitHub Project. A `docs/backlog-config.local.json` overrides it when present
