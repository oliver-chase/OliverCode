# OliverCode Agent Rules

This file loads in every session on this machine, from any directory, via the
`~/.claude/CLAUDE.md` symlink. **Your working directory is usually NOT OliverCode**, so every
path below resolves from wherever you are:

- `$OC/...` means a path inside the OliverCode repo. Resolve `$OC` once, when you first need
  it, and verify it — an uninstalled or moved symlink resolves to `.`, which would silently
  point at the wrong repo:
  ```bash
  OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
  [ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed at ~/.claude/CLAUDE.md — see its docs/ADOPTING.md"
  ```
  No hardcoded machine or home paths.
- Bare paths (`scripts/validate.sh`, `docs/`) mean the repo you are currently working in.
  Each fleet repo ships its own. They are not OliverCode's.

## Memory
Durable facts, state, and decisions live only in `$OC/.claude-optimization/memory/` (`MEMORY.md`,
`USER.md`) and `$OC/.claude-optimization/state/current_state.md`. Never write to Claude Code's
own built-in auto-memory system (the file-based memory under `~/.claude/projects/.../memory/`
that a session's own instructions describe). That store lives outside the vault, keyed to one
machine's install, and does not travel across accounts or laptops. If a session's own prompt
tells you to maintain it, decline and write the fact to `.claude-optimization/` instead.
Read `MEMORY.md` and `USER.md` before work that depends on earlier decisions or the owner's
preferences.

## Voice
@~/.claude/VOICE.md

This voice applies to every reply in chat as well as every file, and it overrides any default
instruction to keep replies short. It ships as `$OC/docs/VOICE.md`, and `olivercode install` links it
to `~/.claude/VOICE.md`.

A skill's questions, options and messages, and any document you draft, go out word for word
as the skill gives them.

## Before you change structure or move a skill
- Structural change to a repo: read `$OC/docs/FRAMEWORK-BOUNDARY.md` first.
- Installing, creating, or moving ANY skill or agent file, in OliverCode, `~/.claude/` or any
  repo: read `$OC/docs/SKILLS-PLACEMENT.md` first. Each layer has one home.

## Development practice
Always on. `$OC/core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` holds the full sequence and its
working rules. Three triggers apply in every session:
- Something broken, failing or slow: run the `diagnosing-bugs` skill loop before changing code
- A multi-commit build session ending: run the `deep-review` skill before closing
- Writing a README or repo doc: follow `$OC/docs/DOCUMENTATION-STANDARD.md` for its structure and
  `$OC/docs/VOICE.md` for its words

## Pre-Commit
Run the current repo's own validation before committing, never OliverCode's. Usually
it is `scripts/validate.sh`, otherwise an npm script (`validate` or `check`). Read that repo's
CLAUDE.md or package.json to find which. Do not assume the filename.
Follow the locked process in `$OC/core/contracts/EXECUTION_CONTRACT.md`.

## Enforcement
`.githooks/pre-commit` is the only layer git itself enforces, and it fails open when a repo's
`core.hooksPath` is unset. `$OC/docs/GOVERNANCE.md` lists the gates, and `$OC/scripts/olivercode health`
finds a repo whose hooks stopped running.

## Working inside OliverCode
`docs/FEATURE-MAP.md` maps every script, layout and config path. Open work lives in the GitHub
Project that `docs/backlog-config.json` names.
