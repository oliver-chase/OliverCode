# OliverCode Agent Rules

This file loads in every session on this machine, from any directory, via the
`~/.claude/CLAUDE.md` symlink. **Your working directory is usually NOT OliverCode**, so every
path below is written to resolve from wherever you are:

- `$OC/...` means a path inside the OliverCode repo. Resolve `$OC` once, when you first need
  it, and check it — an uninstalled or moved symlink resolves to `.`, which would silently
  point at the wrong repo:
  ```bash
  OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
  [ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed at ~/.claude/CLAUDE.md — see its docs/ADOPTING.md"
  ```
  No hardcoded vault or home paths.
- Bare paths (`scripts/validate.sh`, `docs/`) mean the repo you are currently working in.
  Each fleet repo ships its own; they are not OliverCode's.

## Voice
Compressed, high-signal. No filler. Caveman mode (`caveman` plugin, full intensity) active by
default from the first response, every session — not trigger-based, don't wait for "less
tokens" or "be brief" to turn it on. Off only on explicit "stop caveman." Code/commits/PRs/
security warnings written normal, per the plugin's own rules.

## Before you change structure or move a skill
- Structural change to a repo: read `$OC/docs/FRAMEWORK_BOUNDARY.md` first.
- Installing, creating, or moving ANY skill or agent file (in OliverCode, `~/.claude/`, or any
  repo): read `$OC/docs/SKILLS-PLACEMENT.md` first — one home per layer, ledger write in the
  same session.

## Development Practice
Always-on while working, not on request. Full sequence — gap analysis, spec, priority,
build/verify/commit loop, separate QA pass, simplify —
`$OC/core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md`. The rules below are the ones you
apply constantly; that contract is the order they run in.
- Something broken/failing/slow? Run the `diagnosing-bugs` skill loop — never patch on a guess.
- Multi-commit build session ending? Run the `deep-review` skill (single review agent,
  simplify, remove-don't-archive cleanup, live re-verify, tracker update) before closing.
- Simplify as you go: after any nontrivial change, ask what the diff makes redundant
  (`/simplify`, `/code-review` before commit).
- Comment the DECISION, not the mechanism: name the defect the code prevents, give it an
  `AREA-TOPIC-N` id, index it in that repo's own DECISIONS ledger, and gate the index in
  `check` (`$OC/core/contracts/CODE_INTENT_STANDARD.md`). Never hand-maintain a volatile
  number (test counts, coverage, timings) in prose — state the command instead; dated
  measurements go in the backlog tracker once, with their date.
- Ablate before trusting a test: remove the guard, confirm it goes red, restore. A test that
  stays green without the code it protects reports confidence it has not earned.
- Folder structure stays clean and minimal — no new top-level dirs without a contract reason
  (`$OC/core/contracts/PROJECT_STRUCTURE_STANDARD.md`).
- Before you write ANY doc, README, or non-trivial comment: `$OC/docs/WRITING_PROCESS.md`.
  Think, write plainly, then QA. A length gate is QA — writing to a cap produces prose that
  passes and still says in three sentences what one carries.
- Documentation robust but manageable: one concept one home, pointers elsewhere. The QA pass
  is `$OC/docs/DOCUMENTATION_STANDARD.md` (locked outline, voice, naming, GitHub About),
  applied by the `writing-documentation` skill, and its Voice rules govern comment prose too.
  Docs sync in the same commit as the change, always.
- Token efficiency is a design constraint: prefer deterministic scripts over LLM calls, short
  pointers over restated rules.

## Pre-Commit
Run the current repo's own canonical validation before committing, never OliverCode's.
Usually `scripts/validate.sh`; where that file does not exist the repo runs validation
through its own npm script instead (`validate`, or `check`). Confirm which from that repo's
CLAUDE.md or package.json rather than assuming the filename — an agent that assumes, finds
nothing, and moves on has skipped validation without noticing.
Follow: CODE→DOCS→AUDIT→QA→GATE→COMMIT→PUSH.

## Enforcement
`.githooks/pre-commit` is the only mechanically-enforced layer (ten gates here, eight in a
repo that adopts the framework -- `$OC/docs/GOVERNANCE.md` has the per-repo table).
It is installed per repo via `core.hooksPath`; if that config is unset or points at a missing
directory, **git runs no hooks at all and says nothing** — the gates fail open. `$OC/scripts/olivercode health`
is what detects that; `$OC/scripts/olivercode sync-hooks` repairs it.

Everything else in this file and in `CONTRIBUTING.md` is instruction text — see CONTRIBUTING.md's
"Enforcement Reality" section before assuming a written rule is unbreakable.

## OliverCode's own surface (only when working IN OliverCode)
- `bash scripts/validate.sh` — gates, doc/code consistency, reference integrity, tests
- `python3 scripts/audit-staleness.py` — flags fleet repos past 30 unreviewed commits
- `scripts/qa/full-qa-pass.sh --target <repo>` / `scripts/qa/run-on-repo.sh` — QA sweep
- Layout: `core/` (contracts, personas, templates, workflows), `skills/` (flat, one dir per
  skill), `shared/` (manifest, policies), `scripts/` (launcher + gates), `docs/`
- Enforcement config: `local/repo-profiles.json` (gitignored, real fleet) or
  `shared/repo-profiles.example.json` (tracked placeholder), `shared/task-policies/`,
  `scripts/orchestration-gatekeeper.py`
