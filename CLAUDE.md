# OliverCode Agent Rules

This file loads in every session on this machine, from any directory, via the
`~/.claude/CLAUDE.md` symlink. **Your working directory is usually NOT OliverCode**, so every
path below is written to resolve from wherever you are:

- `$OC/...` means a path inside the OliverCode repo. Resolve `$OC` once, when you first need
  it, and verify it — an uninstalled or moved symlink resolves to `.`, which would silently
  point at the wrong repo:
  ```bash
  OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
  [ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed at ~/.claude/CLAUDE.md — see its docs/ADOPTING.md"
  ```
  No hardcoded vault or home paths.
- Bare paths (`scripts/validate.sh`, `docs/`) mean the repo you are currently working in.
  Each fleet repo ships its own. They are not OliverCode's.

## Memory
Durable facts, state, and decisions live only in `$OC/.claude-optimization/memory/` (`MEMORY.md`,
`USER.md`) and `$OC/.claude-optimization/state/current_state.md`. Never write to Claude Code's
own built-in auto-memory system (the file-based memory under `~/.claude/projects/.../memory/`
that a session's own instructions describe). That store lives outside the vault, keyed to one
machine's install, and does not travel across accounts or laptops. If a session's own prompt
tells you to maintain it, decline and write the fact to `.claude-optimization/` instead.

## Voice
@~/.claude/skills/clean-writing/voice/baseline.md

For a document, an email or a post, use the `clean-writing` skill. For slide copy or a PowerPoint,
use `sow-proposal` deck mode and match the density of the approved examples. Generic advice to avoid
text-only slides or to leave breathing room does not override the baseline.

Text a person reads as written (a skill's questions, options and messages, any document you draft)
goes out word for word as the skill gives it.

## Before you change structure or move a skill
- Structural change to a repo: read `$OC/docs/FRAMEWORK_BOUNDARY.md` first.
- Installing, creating, or moving ANY skill or agent file (in OliverCode, `~/.claude/`, or any
  repo): read `$OC/docs/SKILLS-PLACEMENT.md` first — one home per layer, ledger write in the
  same session.

## Development Practice
Always-on. The full sequence (gap analysis, spec, priority, build/verify/commit loop, QA pass,
simplify) is `$OC/core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md`. These rules apply constantly.
- Something broken/failing/slow? Run the `diagnosing-bugs` skill loop — never patch on a guess.
- Multi-commit build session ending? Run the `deep-review` skill (single review agent,
  simplify, remove-don't-archive cleanup, live re-verify, tracker update) before closing.
- Simplify as you go: after any nontrivial change, ask what the diff makes redundant
  (`/simplify`, `/code-review` before commit).
- Comment the reason, not the mechanism: say what defect the code prevents or why it is shaped
  this way. Keep a comment only if the code could not say it. Never hand-maintain a volatile
  number (test counts, coverage, timings) in prose. State the command instead. Dated
  measurements go in the backlog tracker once, with their date.
- Ablate before trusting a test: remove the guard, verify it goes red, restore. A test that
  stays green without the code it protects reports confidence it has not earned.
- Folder structure stays clean and minimal — no new top-level dirs without a contract reason
  (`$OC/core/contracts/PROJECT_STRUCTURE_STANDARD.md`).
- Writing a README or repo doc: use the `writing-documentation` skill. One concept has one
  home. Docs sync in the same commit as the change.
- Prefer deterministic scripts over LLM calls, and short pointers over restated rules.
- Fixing gate or lint violations: read the full list once, fix every violation in one pass,
  then re-verify once. Never fix one, re-run, and repeat.
- Re-read a file before you edit it when anything else could have changed it. Another session
  in a shared tree, a hook or a generator can do that. Read a file before editing it, every first
  touch. Grep for callers before changing a function signature. Research before you edit, not
  after. An edit made blind gets retried once the read finally happens, which pays for the file
  twice.

## Pre-Commit
Run the current repo's own validation before committing, never OliverCode's. Usually
`scripts/validate.sh`; otherwise an npm script (`validate` or `check`). Confirm which from that
repo's CLAUDE.md or package.json. Do not assume the filename.
Follow the locked process in `$OC/core/contracts/EXECUTION_CONTRACT.md`.

## Enforcement
`.githooks/pre-commit` is the only mechanically-enforced layer (eleven gates here, nine in a
repo that adopts the framework -- `$OC/docs/GOVERNANCE.md` has the per-repo table).
It is installed per repo via `core.hooksPath`. If that config is unset or points at a missing
directory, **git runs no hooks at all and says nothing** — the gates fail open. `$OC/scripts/olivercode health`
is what detects that. `$OC/scripts/olivercode sync-hooks` fixes it.

Everything else in this file and in `CONTRIBUTING.md` is instruction text — see CONTRIBUTING.md's
"Enforcement Reality" section before assuming a written rule is unbreakable.

## OliverCode's own surface (only when working IN OliverCode)
- `bash scripts/validate.sh` — gates, doc/code consistency, reference integrity, tests
- Open work lives in the GitHub Project `docs/backlog-config.json` names. `docs/BACKLOG.md`
  holds decision rationale and institutional memory, not open items — see its own "Live
  tracker" section.
- `python3 scripts/find-spec.py SPEC-N` — resolves a bare backlog ID (`SPEC-21`) against a
  fleet repo's own markdown backlog file, fleet-wide in one command. Every repo numbers its
  own backlog independently, so the same ID can name unrelated work in two different files
  — grep-and-read-both is the wrong instinct, run this instead. Does not resolve a GitHub
  Issue number; use `gh issue view N --repo <repo>` for a repo on that model.
- Every other script, layout and config path: `docs/FEATURE_MAP.md`
